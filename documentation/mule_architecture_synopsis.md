# Project Mule: Architecture & State Synopsis

**Purpose of this Document:**
This document serves as a complete brain-dump and architectural synopsis for "Project Mule". It is designed to perfectly prime an AI assistant in a new session, providing all necessary context, architectural decisions, hardware quirks, and the exact current state of the codebase so that work can resume seamlessly on **Phase 4: Final Hardening**.

---

## 1. Project Overview & Hardware Context
**Project Mule** is a custom high-speed data transfer protocol designed to reliably transmit large files (e.g., 400KB+ AVIF images) over half-duplex RF links using **Digi XBee Pro 900HP** modules.

### Hardware Setup:
- **Base Station**: A Raspberry Pi connected to an XBee via a standard USB-to-UART adapter (`/dev/ttyUSB0`).
- **Mule (Remote Node)**: A Raspberry Pi communicating with its XBee directly over the **SPI bus** (`spidev0.0`) to bypass UART clock drift and achieve a physical interface speed of 3 MHz.
- **RF Configuration**: The XBees are configured for `200 Kbps` RF data rate (`AT TR 1`).
- **Critical Wiring on Mule**: To prevent the SPI bus from locking up the XBee natively when a script terminates abruptly, the XBee's physical `/RESET` pin is wired to the Pi's **GPIO 17**. The `XBeeSPI` driver physically pulls this pin low on initialization to forcibly shatter any hanging silicon locks. The `/ATTN` pin is wired to **GPIO 25**.

---

## 2. The Protocol: "Windowed Blast Mode"
To exceed the theoretical limits of standard API frame-and-ACK ping-pong, we engineered a custom "Blast Mode".

- **SPI Emancipation**: The Mule uses a custom `xbee_spi.py` driver (bypassing the `digi-xbee` library entirely) to push data into the XBee at 3,000,000 bps.
- **Windowed Transmission**: `uploader.py` chunks files into 200-byte payloads. It blasts an entire "Window" (e.g., 128 packets) continuously before halting to wait for a single hardware synchronization `SSACK` from the Base Station.
- **Micro-Pacing**: Because 3 MHz SPI vastly outpaces the 200 Kbps RF drain rate, `uploader.py` implements a strict `time.sleep(0.014)` pause between every single SPI packet injection to perfectly pace the hardware buffer and prevent overflow deadlocks.

---

## 3. Dynamic A-Spectrum & Selective Repeat Lite
To maintain high throughput (hitting ~9.27 KB/s) while remaining resilient to deep-space RF interference, the protocol employs two advanced dynamic recovery mechanisms:

### A. Dynamic A-Spectrum (The Gearbox)
If the Mule suffers a complete window timeout (the Base Station never responds), the Pi mathematically "downshifts" its window size (`128 -> 64 -> 32 -> 16`). 
Instead of sending a traditional 14-byte API header, it uses a 3-byte Bypass Header (`0xA0`, `0xA1`, `0xA2`, `0xA3`) which dynamically informs the Base Station (`session_manager.py`) of the new window geometry.

### B. Selective Repeat Lite (Targeted Micro-Bursts)
If the Base Station receives a window but detects "Swiss-Cheese" holes (missing packets due to brief RF drops):
1. The Base calculates the exact missing sequence indices.
2. It generates a dense binary 1-bit map (byte array) where `1` = missing.
3. It transmits a `TASK_ASSIGN(REQUEST_PKT)` back to the Mule containing this bitmap.
4. The Mule's `wait_for_ssack_or_request()` multiplexer decodes this bitmap.
5. The Mule explicitly halts the main loop, maps the bits back to absolute sequence integers, and fires a **Micro-Burst**, transmitting *only* the specific missing chunks at the `0.014s` pace.
6. **Crucial Exploit**: The Mule appends the absolute `end_seq` of the window to the back of the Micro-Burst array. This forces the Base Station's native `seq % window_size == 0` modulo logic to trigger, causing it to evaluate the patched array and finally send the standard `SSACK` to resume normal transmission.

---

## 4. Codebase Structure & Key Files
All primary code resides in `/home/kickit2/gemini/antigravity/scratch/`.

- **`faux_base/protocol.py`**: Defines packet structs, Message Types, and CRC logic. *Note: A-Spectrum bypass variables were removed from the PacketType Enum to prevent CRC corruption, mapped instead to `bypass_window_size`.*
- **`faux_base/session_manager.py`**: The Base Station state machine. Listens on `/dev/ttyUSB0`. Handles handshakes, Swiss-Cheese hole detection, bitmap synthesis for `REQUEST_PKT`, and includes a 60-second garbage collector thread to prune stale sessions.
- **`faux_base/file_handler.py`**: Reassembles the file byte streams and validates the final byte payload length against the `expected_size` before evaluating the CRC checksum to prevent EOF truncation.
- **`mule_code/uploader.py`**: The Pi Uploader logic. Chunks files, parses `REQUEST_PKT` bitmaps, manages the micro-burst patch logic, and handles the `MAX_RETRIES` deadlock abort loop.
- **`mule_code/xbee_spi.py`**: Custom raw SPI device driver using `spidev` and `lgpio`/`RPi.GPIO` for the `/ATTN` and `/RESET` pins.
- **`serial_killer.py`**: Utility script used to aggressively rip deadlocked Python threads off GPIO 25 and /dev/ttyUSB0.

---

## 5. Deployment / Test Execution Environment
- The Base Station runs natively on the x86 host.
- The Mule runs on a remote Raspberry Pi (`testzero.local.lan`), accessed via SSH.
- **Environment Quirk**: When running diagnostic tests via SSH, Python's `stdout` must be unbuffered (`-u` flag) to prevent the pipeline from hanging silently, i.e., `python3 -u main.py` and `sshpass -p test ssh -tt -o StrictHostKeyChecking=no kickit2@testzero.local.lan "sudo python3 -u uploader.py"`.

---

## 6. Completed Phases: Hardening & Architecture Evolution
The core architecture is now fully validated and conceptually expanded to support routing and adaptive links.

### Phase 4 & 5 Enhancements (Complete)
- **Interrupt-Driven RX Processing:** Migrated the Mule's SPI `read_available` from CPU-intensive polling to a safe `GPIO.add_event_detect` background queue, eliminating processing delay.
- **Maximum XBee API Pacing:** MTU is set to 240, yielding exactly a 235-byte physical payload payload (`BLAST_PAYLOAD_SIZE = 235`). This directly matches the absolute maximum 256-byte frame buffer of the XBee modules.

### The Empirical Pacing Curve (Equation)
Through binary search benchmarking, we discovered a core physical hardware limitation: **The XBee Processor mandates a hard fixed 14ms internal delay minimum regardless of payload size.** Bypassing this overflows the buffer and breaks the RF link.
Using these bounds, `uploader.py` dynamically paces its SPI injection according to an exact piecewise formula:
```python
# The piecewise delay calculation
curve_base = 0.014
emp_pacing = curve_base + ((size - 200) * 0.0002) if size > 200 else curve_base
time.sleep(emp_pacing)  # Operates strictly at 21ms for maximum 235-byte chunks
```
This formula eliminated all buffer overruns natively, stabilizing the continuous transfer rate exactly at **9.91 KB/s**.

### Phase 10 Enhancements (Unified Mesh Architecture)
To handle 900MHz range limits and antenna disparities, the architecture implements the following advanced features:
- **Asymmetrical Power Negotiation**: Mules initiate a 10K `REQ_XFER` at power level `PL=0`, iteratively scaling up to `PL=4` until the Base Station acknowledges. Crucially, the Base echoes the Mule's successful PL back in its `APPROVE` packet. Based on incoming RSSI, both nodes can independently issue `0x0C POWER_ADJUST` commands to maximize link stability before shifting to 200 Kbps.
- **Dual-Radio Base Station**: The Base daemon simultaneously manages two radios: `/dev/ttyUSB0` (locked to 10K for all handshakes/TDM) and `/dev/ttyUSB1` (locked to 200K for Blast payloads). The 10K radio explicitly hands off the 200K radio's 64-bit MAC address in the `APPROVE` payload.
- **Store & Forward Relays**: Mules can bypass the Base via hardware dip-switches (inverted pull-up logic) and route 200K payloads directly to an intermediate Relay Station bucket. Relays execute the dynamic window protocol but do not parse files; they save raw `.dat` streams and allow the Base Station to poll them via `0x0D POLL_RELAY` ~1 hour later.

### Phase 12 & 13 Enhancements (Security & Fleet Scheduling)
- **Cryptographic File Deletion (Phase 12)**: The payload size is inherently tracked in the `.AVIF` suffix (e.g., `IMG0004_SZ4512345`). The Base commands deletions by injecting this size into the `0x0A DELETE_FILE` execution. The Mule cross-checks this size iteratively against the camera FTP `SIZE` command natively. If sizes are adrift, the pipeline aborts the erasure. 
- **Time-Division Multiplexed (TDM) Fleet Control (Phase 13)**: The Base Station divides the 24-hour cycle by the number of active node heartbeats registered in the last 48 hours. It sequentially allocates each Mule a specific Wake Window via the `SET_SCHEDULE` command over SPI.

### Phase 15 Enhancements (Ultra-Sleep Hardware)
The Mule transitions into a 0mA standby draw using a robust three-tier architecture:
- **ATtiny84** manages the high-side 5V Buck Enable pin. The Pi drives a dedicated GPIO Watchdog PIN high while active.
- When the Linux OS terminates cleanly (`poweroff`), the Watchdog Pin physically drops LOW. The ATtiny observes this falling edge and instantly drops the 5V `EN` line, completely cutting Pi Zero power without filesystem corruption.

### Phase 17 Enhancements (Mid-Stream Power Scaling)
- **Iterative Signal Surging**: If the Mule encounters `consecutive_failures == 3` during an active 200K Data Blast (either missing `SSACK` patches or complete generic drops), the `uploader.py` logic natively issues an `ATPL` shift to the underlying XBee driver.
- The RF transceivers scale power upward dynamically (+5 dBm steps) *during* the file loop to actively punch through sudden environmental interference without ever renegotiating or tearing down the master file handshake.

---

## 7. Operational Workflow & Environment Quirks

Because the Mule exists remotely and utilizes physical GPIO pins, specific commands are required to avoid hidden deadlocks, authentication hangs, or ghost Python states. **Username:** `kickit2` | **Password:** `test` | **Mule Hostname:** `testzero.local.lan`

**A. Clearing Deadlocks & Ghost Pins on Mule:**
If a remote script crashed or was cancelled, standard `CTRL+C` leaves the `spidev` and GPIO 25/17 locked in memory holding the XBee hostage. Always explicitly kill all processes before running a new test:
```bash
killall python3 ; sshpass -p test ssh -tt -o StrictHostKeyChecking=no kickit2@testzero.local.lan "sudo killall python3" ; sleep 2
```

**B. Running the Fleet Manager (Local Host TestZero):**
The architecture is designed to execute locally on the hardware buffer (`/dev/ttyACM0`) using an unbuffered python environment.
```bash
sudo python3 -u MuleCommander/fleet_manager.py
```

**C. Active Base Station (x86 Server):**
The base station requires `pyserial`. Ensure clean runs by mapping output directly to the logger arrays:
```bash
faux_base/.venv/bin/python3 -u faux_base/main.py > base_test_run.log 2>&1
```



## XI. Transmission Boundary Gap Constraints

The Woods-Net high-speed transfer architecture relies on precise execution timing to interact safely with the 200 Kbps physical UART interfaces. Two critical static mathematical gaps must be preserved in the `uploader.py` file to prevent irrecoverable radio deadlocks on the Base Station receiver.

### 1. The Pre-Blast Transition Buffer (0.50 Seconds)
When the PyXBee Base Station acknowledges an incoming `REQ_XFER` handshake, it executes `device.set_parameter("PL", ...)`. This is a *blocking* Python thread that forces the `ttyUSB0` loop to sleep while it waits for an `0x88` AT Command hex response from the XBee hardware. 

If the Mule transmits the massive `256`-byte data payload arrays immediately upon receiving the `APPROVE` ACK, the massive high-speed 200 Kbps pipeline will violently hit the Base Station's locked UART loop before PyXBee can wake up. The kernel serial buffer will instantly overflow, irreversibly amputating the incoming `0x7E` headers and trapping the PyXBee decoder in a fatal `CRC Error` deadlock.

* **Requirement:** `time.sleep(0.50)` **MUST** be executed natively inside the `uploader.py` pipeline precisely mapped between the final local `TR=1` (200 Kbps) shift and the primary payload blast array to protect the remote PyXBee parser.

### 2. The Inter-File Saturation Buffer (1.50 Seconds)
When transmitting multiple `.AVIF` files back-to-back, the Base Station requires a micro-moment to execute garbage collection and flush its internal tracking variables (`active_transactions`) after delivering the final `CONF_XFER` acknowledgment string. Attempting to rapid-fire a subsequent `REQ_XFER` handshake string without delay will create a `status not ok` mid-stream transaction collision, locking the file transfer stream in a zombie state.

* **Requirement:** `time.sleep(1.5)` **MUST** be executed natively inside `uploader.py` mapping at the bottom of the `for f in files:` blast iteration constraint.

*End of Synopsis.*
