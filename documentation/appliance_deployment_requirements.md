# MULE DEPLOYMENT & CUSTOM APPLIANCE REQUIREMENTS
Project: WOODS-NET Remote Trail Camera Network

*This document explicitly tracks all low-level system requirements, binaries, libraries, and hardware interfaces required to build a standalone, single-user embedded Linux appliance (e.g., Buildroot or Yocto) for the Mule architecture, specifically moving AWAY from virtual environments and standard desktop distributions.*

## 1. Core Operating System & Shell
*   **User Space**: Single-user (root/admin) space. No need for `sudo` prefixes on commands.
*   **Init System**: `systemd` or standard `init` to trigger `MuleCommander` strictly on boot.
*   **Filesystem Constraints**:
    *   `/media/cam_grabs/` strictly configured as an ephemeral `tmpfs` (RAM disk) mounted via `/etc/fstab` to preserve SD card telemetry and power efficiency.
    *   Read-only root filesystem with a small persistent overlay (optional, but highly recommended for appliance longevity).

## 2. Hardware Mapping & Interfaces (Kernel Modules)
*   **Mule Remote Nodes (Raspberry Pi Zero W / 2W)**:
    *   Strictly utilized for power-constrained environments.
*   **Base Station (Raspberry Pi 4 - 4GB)**:
    *   Explicitly chosen for compute headroom, allowing future extensibility (Mosquitto/MQTT weather brokers, UI dashboards, and local machine-learning/computer-vision tasks on incoming images).
    *   Maintains the identical 40-pin GPIO footprint as the Zero, ensuring our custom Broadcom `spidev` and `RPi.GPIO` bit-banging drivers (`xbee_spi.py`) execute identically without ported Allwinner/Orange Pi timing bugs.
*   **SPI (Serial Peripheral Interface)**:
    *   Kernel module: `spidev` MUST be enabled.
    *   Parameters: `spi-bcm2708` or modern `spi-bcm2835` depending on the kernel.
    *   Usage: XBee API Frame communication at 3MHz+.
*   **I2C (Inter-Integrated Circuit)**:
    *   Kernel module: `i2c-dev` and `i2c-bcm2835` MUST be enabled.
    *   Usage: Communicating with the DS3231 RTC (`rtc_manager.py`) and the ATtiny84 power management sub-controller.
*   **UART (Serial)**:
    *   Primary hardware serial disabled for console (if pins 14/15 are used) or explicitly routed to an alternate interface for debugging.
*   **GPIO**:
    *   Access to physical hardware pins (e.g., Pin 25 for SPI ATTN, Pin 17 for XBee Reset).
    *   Library: `libgpiod` or raw `sysfs` GPIO interface.

## 3. System Utilities & Binaries
*   **Wi-Fi Management**:
    *   `wpa_supplicant`: Required for bridging to the Ceyomur camera's AP.
    *   `wpa_cli`: Required for scripting `wpa_supplicant` state changes.
    *   `iproute2` (for `ip link`, `ip addr`): Network interface management.
*   **Bluetooth Control (CRITICAL)**:
    *   **BlueZ Suite**: Requires the full BlueZ protocol stack.
    *   `bluetoothctl`: The interactive manager used heavily by `ble_scout.py`.
    *   *CRITICAL WARNING*: The team spent days attempting to force modern Buildroot to compile `bluetoothctl` without success. It actively refuses. **Therefore, the official strategy requires explicitly selecting an older, pre-deprecation version of BlueZ** when constructing the Buildroot environment.
*   **Power / Lifecycle**:
    *   `shutdown`, `poweroff`, `reboot` utilities.

## 4. Native Libraries (C/C++)
*   **libavif**: If the `image_crusher.py` migrates processing entirely locally or requires specific system-level bindings, `libavif` and its dependencies (e.g., `libaom` or `libdav1d`) must be compiled into the image.
*   **ImageMagick / VIPS (Optional)**: Depending on the backend `Pillow` delegates to for fast down-sampling.

## 5. Python Environment (Global Install)
*Since we are ditching `.venv`, these must be installed directly into the system's global Python `site-packages`.*
*   **Python Interpreter**: Python 3.9+ (Optimized/Stripped).
*   **PyPI Packages**:
    *   `spidev`: Essential C-bindings for the SPI kernel module.
    *   `smbus2`: Essential for purely user-space I2C communication (DS3231 / ATtiny).
    *   `requests`: HTTP communication for the Novatek Camera API (Port 80).
    *   `pillow` (PIL): High-performance image buffer manipulation (resizing/cropping).
    *   `pillow-avif-plugin`: Crucial extension for `Pillow` to write highly compressed chunkable `.avif` data.
    *   *(Note: The `digi-xbee` library is purposefully EXCLUDED on the Mule as we have reverse-engineered the raw SPI bit-banging protocol.)*

## 6. Execution Flow Considerations
*   **Shattering Ghost Locks**: `fleet_manager.py` uses `pgrep python3` to kill zombie threads. If the script is compiled via PyInstaller, it will run as a binary (e.g., `/usr/bin/mule_core`) instead of `python3`, requiring an update to the `subprocess.run(kill...)` logic to target the executable's real process name.
*   **Absolute Paths**: All scripts currently assume relative paths or specific `/home/kickit2/` structures. In an appliance, variables like `/media/cam_grabs/` (tmpfs) must be hardcoded and verified at boot. 

## 7. The Buildroot / Yocto Strategy
*   We will require a custom `defconfig` outlining exactly which wireless drivers (`brcmfmac` for the Pi Zero W), crypto libraries (for WPA2), and utilities (BlueZ) are physically compiled into the `zImage` kernel/`rootfs`.
## 8. Hardware Power Delivery Architecture (The Ultra-Sleep Flow)
*   **Standby/Logic Power (Always-On 3.3V)**: 
    *   Requires an **Ultra-Low Quiescent Current ($I_{Q}$) Buck Regulator** stepping 12V down to ~3.3V.
    *   This continuously supplies the ATtiny84 and the DS3231 RTC, ensuring extreme battery efficiency.
*   **Compute Power (Switched 5V)**:
    *   A secondary High-Current Buck Regulator (5V at 3A peak) drives the Raspberry Pi Zero.
    *   The **Enable (EN) pin** on this 5V regulator is the master control.
*   **Radio Power Isolation (Switched 3.3V)**:
    *   The XBee S3B runs on 3.3V but cannot stay powered during sleep.
    *   A dedicated Logic-Level P-Channel MOSFET (or Load Switch) sits between the Always-On 3.3V source and the XBee's VCC pin.
*   **The "Ultra-Sleep" State Machine Flow**:
    1.  **Deep Sleep**: 3.3V regulator is ON. ATtiny84 and RTC are powered (but asleep). 5V regulator is OFF. XBee is OFF. System draws sub-microamps.
    2.  **Wake Trigger**: DS3231 RTC Alarm drops the INT pin LOW, waking the ATtiny84.
    3.  **Boot Compute**: ATtiny84 pulls the 5V Regulator's `EN` pin HIGH. The Raspberry Pi Zero boots.
    4.  **Handoff**: The Pi boots and immediately asserts a specific GPIO pin HIGH (e.g., via `/boot/config.txt` overlay).
    5.  **Watchdog state**: The ATtiny detects this GPIO pin go HIGH. The ATtiny now knows the Pi is alive. The ATtiny stays awake (clocked extremely low to save power) and maintains the 5V `EN` pin HIGH.
    6.  **Radio Booting**: The Pi asserts a separate GPIO pin to turn on the XBee MOSFET, providing 3.3V to the radio only when it's actively needed.
    7.  **Mission Execution**: Images are crushed, files are uploaded.
    8.  **Shutdown Prep**: The Pi calculates the next wake time, programs the DS3231 RTC Alarm, and pulls the XBee MOSFET pin LOW, killing radio power.
    9.  **Enter Ultra-Sleep**: The Pi executes a standard OS `poweroff`.
    10. **The Final Cut**: As the Pi fully halts, the kernel drops the specific GPIO pin LOW. The ATtiny detects this falling edge, knows the Pi is safely dead, drops the 5V `EN` pin to kill the compute rail, and returns to Deep Sleep.
