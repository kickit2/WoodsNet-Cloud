/*
 * ATtiny84 Power Manager for Raspberry Pi Zero W "Mule"
 * 
 * Target MCU: ATtiny84A
 * Clock: 1MHz Internal Oscillator (for maximum power savings)
 * 
 * Architecture:
 * - The ATtiny84 is powered directly from the battery (VCC always on).
 * - A P-Channel MOSFET acts as the main power switch for the Pi Zero's 5V rail.
 * - The MOSFET Gate is pulled HIGH by default via a 10k resistor (keeping the Pi OFF).
 * - The DS3231 RTC SQW/INT pin (Active-Low) triggers the ATtiny84's external interrupt to wake up.
 * - The ATtiny84 pulls the MOSFET Gate LOW to turn the Pi ON.
 * - A GPIO from the Pi goes HIGH to signal "I am done, kill my power".
 * 
 * Pin Mapping (ATtiny84 Physical Pins):
 * Pin 1 (VCC)       -> Battery + (1.8V to 5.5V)
 * Pin 14 (GND)      -> Battery GND
 * Pin 5 (PA5 / D5)  -> DS3231 SQW/INT (Active-Low Interrupt from RTC)
 * Pin 6 (PA4 / D4)  -> Pi "Done" Signal (Input from Pi GPIO, e.g., GPIO 22)
 * Pin 7 (PA3 / D3)  -> P-Channel MOSFET Gate (Output, Active-Low = Power ON)
 */

#include <avr/sleep.h>
#include <avr/interrupt.h>

// --- Pin Definitions (Arduino Core for ATtiny) ---
const int PIN_RTC_INT = 5;  // PA5: Interrupt from DS3231
const int PIN_PI_DONE = 4;  // PA4: Signal from Pi saying it's halting
const int PIN_MOSFET  = 3;  // PA3: Drives the MOSFET Gate

// State machine flags
volatile bool wake_requested = false;
bool pi_is_powered = false;

// Interrupt Service Routine for the RTC INT pin
// This just sets a flag to wake the main loop; we don't do heavy logic inside an ISR
ISR(PCINT0_vect) {
  // If the RTC pin goes LOW, we flag a wake request
  if (digitalRead(PIN_RTC_INT) == LOW) {
    wake_requested = true;
  }
}

void setup() {
  // Configure Pins
  pinMode(PIN_MOSFET, OUTPUT);
  // Default state: MOSFET OFF (Gate HIGH)
  digitalWrite(PIN_MOSFET, HIGH);
  pi_is_powered = false;

  pinMode(PIN_RTC_INT, INPUT_PULLUP);
  pinMode(PIN_PI_DONE, INPUT); // Expecting Pi to drive this HIGH when shutting down

  // Configure Pin Change Interrupts for PA5 (RTC INT)
  GIMSK |= (1 << PCIE0);   // Enable Pin Change Interrupts for Port A
  PCMSK0 |= (1 << PCINT5); // Enable PCINT5 (which is PA5 / Pin 5)

  // Turn off unnecessary peripherals to save power (ADC, Timers)
  ADCSRA &= ~(1 << ADEN); // Disable ADC
  
  // Enable global interrupts
  sei();
}

void loop() {
  if (wake_requested && !pi_is_powered) {
    // 1. Wake up sequence initiated by RTC
    wake_requested = false;
    
    // Turn ON the Pi by pulling MOSFET Gate LOW
    digitalWrite(PIN_MOSFET, LOW);
    pi_is_powered = true;
    
    // Wait for the Pi to boot and pull the 'Done' pin LOW initially if floating
    delay(5000); 
  }

  if (pi_is_powered) {
    // 2. Pi is running. Wait for the "Done" signal
    // The Python script on the Pi should drive GPIO 22 HIGH when it's finished,
    // right before calling `os.system("sudo halt")`.
    
    if (digitalRead(PIN_PI_DONE) == HIGH) {
      // 3. Pi signaled it is shutting down.
      // Give the OS 20 seconds to safely unmount the SD card and halt.
      delay(20000); 
      
      // Cut the power
      digitalWrite(PIN_MOSFET, HIGH);
      pi_is_powered = false;
      
      // Clear any pending interrupts that might have queued while awake
      GIFR |= (1 << PCIF0);
    }
  }

  // 4. If the Pi is OFF, go into Deep Sleep
  if (!pi_is_powered) {
    set_sleep_mode(SLEEP_MODE_PWR_DOWN);
    sleep_enable();
    sleep_cpu(); // MCU halts here, drawing ~0.1uA until the RTC fires the interrupt
    
    // MCU resumes here after interrupt fires
    sleep_disable();
  }
}
