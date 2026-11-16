#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

#include "config.h"

// Arduino-ESP32 core 3.x replaced the old channel-based LEDC API
// (ledcSetup/ledcAttachPin/ledcWrite(channel,...)) with a new pin-based one
// (ledcAttach(pin,...)/ledcWrite(pin,...)). platformio.ini doesn't pin an
// exact core version, so we detect which one is actually available at
// compile time and use the matching calls, instead of guessing and risking
// a build that fails to compile entirely on the "other" version.
#if defined(ESP_ARDUINO_VERSION_MAJOR) && ESP_ARDUINO_VERSION_MAJOR >= 3
    #define ATLAS_LEDC_NEW_API 1
#else
    #define ATLAS_LEDC_NEW_API 0
#endif

// ===================== SPI (shared by both RFID readers) =====================
#define SPI_SCK 18
#define SPI_MISO 19
#define SPI_MOSI 23

#define ENTRY_SS 5
#define ENTRY_RST 21

#define EXIT_SS 27
#define EXIT_RST 22

MFRC522 entryReader(ENTRY_SS, ENTRY_RST);
MFRC522 exitReader(EXIT_SS, EXIT_RST);

// ===================== LCD =====================
#define LCD_SDA 16
#define LCD_SCL 17

LiquidCrystal_I2C lcd(0x27, 16, 2);

// ===================== RGB status LEDs =====================
#define ENTRY_R 12
#define ENTRY_G 13
#define ENTRY_B 26

#define EXIT_R 14
#define EXIT_G 4
#define EXIT_B 2

// ===================== Servos =====================
// Driven directly through the ESP32's LEDC peripheral instead of the
// ESP32Servo library. That library went through three rounds of fixes
// without resolving the "servo doesn't work" issue, which points at a
// version mismatch between the library and whatever ESP32 Arduino core
// Wokwi is actually compiling against (platformio.ini doesn't pin one).
// Driving LEDC directly removes that whole dependency from the picture.
#define ENTRY_SERVO_PIN 25
#define EXIT_SERVO_PIN 33

const int SERVO_PWM_FREQ = 50;   // standard hobby servo signal frequency
const int SERVO_PWM_RES = 12;    // resolution bits -> duty range 0-4095
const int SERVO_MIN_US = 500;    // pulse width (microseconds) at 0 degrees
const int SERVO_MAX_US = 2400;   // pulse width (microseconds) at 180 degrees

// Only used on the old channel-based LEDC API (core < 3.x).
const int ENTRY_SERVO_LEDC_CHANNEL = 0;
const int EXIT_SERVO_LEDC_CHANNEL = 1;

const int SERVO_CLOSED = 0;
const int SERVO_OPEN = 90;

// Both gates now use this same fixed timing: open on a granted scan, hold
// open for this long, then close automatically. The ultrasonic sensor no
// longer controls gate timing - it's kept only for the idle "someone's
// approaching" message on the LCD, to keep the moving parts to a minimum
// while we get the core RFID -> servo flow rock solid.
const unsigned long GATE_OPEN_TIME = 4000;

// ===================== Buzzer =====================
#define BUZZER_PIN 32

// ===================== Ultrasonic sensor (HC-SR04) — ENTRY gate only for now =====================
// NOTE: on real hardware, HC-SR04 ECHO outputs 5V logic. GPIO34 is 3.3V-only
// and input-only (safe for this use), but on the real board you MUST use a
// voltage divider, e.g. 1k + 2k resistors, between ECHO and GPIO34, or you
// will damage the pin. In the Wokwi simulation this isn't an issue.
#define ULTRASONIC_TRIG_PIN 15
#define ULTRASONIC_ECHO_PIN 34

// Distance (cm) below which we consider someone "approaching" the gate.
// This only drives the idle LCD message right now - it no longer affects
// gate timing (see gateOpen() - both gates use a plain fixed delay).
const int PRESENCE_CM = 25;

// How often (ms) we poll the sensor while idle, just to update the LCD.
const unsigned long PRESENCE_POLL_INTERVAL = 300;

// ============================================================================
// Helpers
// ============================================================================

void rgbOff(int r, int g, int b) {
    digitalWrite(r, LOW);
    digitalWrite(g, LOW);
    digitalWrite(b, LOW);
}

void rgbRed(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(r, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(r);
    Serial.println(" set -> RED");
}

void rgbGreen(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(g, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(g);
    Serial.println(" set -> GREEN");
}

void rgbBlue(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(b, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(b);
    Serial.println(" set -> BLUE (idle)");
}

void lcdShow(String line1, String line2) {
    lcd.clear();

    lcd.setCursor(0, 0);
    lcd.print(line1.substring(0, 16));

    lcd.setCursor(0, 1);
    lcd.print(line2.substring(0, 16));
}

String getUID(MFRC522& reader) {
    String uid = "";

    for (byte i = 0; i < reader.uid.size; i++) {
        if (reader.uid.uidByte[i] < 0x10) {
            uid += "0";
        }

        uid += String(reader.uid.uidByte[i], HEX);
    }

    uid.toUpperCase();
    return uid;
}

bool readCard(
    MFRC522& reader,
    int thisSS,
    int otherSS,
    String& uid
) {
    digitalWrite(otherSS, HIGH);
    digitalWrite(thisSS, HIGH);

    if (!reader.PICC_IsNewCardPresent()) {
        return false;
    }

    if (!reader.PICC_ReadCardSerial()) {
        return false;
    }

    uid = getUID(reader);

    reader.PICC_HaltA();
    reader.PCD_StopCrypto1();

    digitalWrite(thisSS, HIGH);

    return true;
}

void beepSuccess() {
    tone(BUZZER_PIN, 1800, 150);
}

void beepError() {
    tone(BUZZER_PIN, 400, 300);
}

// ============================================================================
// Servo control (direct LEDC, no ESP32Servo library)
// ============================================================================

// Moves the servo on the given pin to the given angle (0-180) by computing
// the correct PWM duty cycle ourselves and writing it straight to the
// ESP32's LEDC peripheral. Built into the ESP32 Arduino core itself - no
// external servo library required.
void setServoAngle(int pin, int angle) {
    int pulseUs = map(angle, 0, 180, SERVO_MIN_US, SERVO_MAX_US);

    long maxDuty = (1L << SERVO_PWM_RES) - 1; // 4095 for 12-bit
    long duty = (long)pulseUs * maxDuty * SERVO_PWM_FREQ / 1000000L;

#if ATLAS_LEDC_NEW_API
    ledcWrite(pin, duty);
#else
    int channel = (pin == ENTRY_SERVO_PIN)
        ? ENTRY_SERVO_LEDC_CHANNEL
        : EXIT_SERVO_LEDC_CHANNEL;

    ledcWrite(channel, duty);
#endif
}

// Attaches a servo pin to the LEDC peripheral, using whichever API
// generation this core actually supports.
void attachServoPin(int pin, int channel) {
#if ATLAS_LEDC_NEW_API
    ledcAttach(pin, SERVO_PWM_FREQ, SERVO_PWM_RES);
#else
    ledcSetup(channel, SERVO_PWM_FREQ, SERVO_PWM_RES);
    ledcAttachPin(pin, channel);
#endif
}

// ============================================================================
// Ultrasonic sensor
// ============================================================================

// Returns distance in cm, or -1 if no echo was received (out of range / error).
long readUltrasonicCM() {
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);

    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);

    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    // 30ms timeout ~= 5m max range, plenty for a gate/doorway sensor.
    long duration = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000UL);

    if (duration == 0) {
        return -1;
    }

    long distanceCm = duration * 0.0343 / 2;
    return distanceCm;
}

// ============================================================================
// WiFi + backend communication
// ============================================================================

bool wifiConnected() {
    return WiFi.status() == WL_CONNECTED;
}

// Blocks up to timeoutMs waiting for WiFi. Used at boot and before a scan
// if the link dropped.
bool connectWiFi(unsigned long timeoutMs) {
    if (wifiConnected()) return true;

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    unsigned long start = millis();
    while (!wifiConnected() && millis() - start < timeoutMs) {
        delay(250);
        Serial.print(".");
    }
    Serial.println();
    return wifiConnected();
}

struct ScanResult {
    bool networkOk;      // false => couldn't get a valid answer from the backend
    bool granted;
    String reason;
    String message;      // short text from the backend, e.g. "Entry granted"
    String studentName;
};

// Asks the backend whether this card may pass. FAILS CLOSED: any network,
// HTTP or parsing problem returns networkOk=false, granted=false.
ScanResult askBackend(const String& uid, const char* direction) {
    ScanResult res = {false, false, "", "", ""};

    if (!wifiConnected()) {
        Serial.println("WiFi down, trying to reconnect...");
        WiFi.disconnect();
        if (!connectWiFi(5000)) {
            res.reason = "wifi_down";
            return res;
        }
    }

    String url = String("http://") + BACKEND_HOST + ":" + BACKEND_PORT + "/gate/scan";

    JsonDocument req;
    req["uid"] = uid;
    req["direction"] = direction;
    String body;
    serializeJson(req, body);

    HTTPClient http;
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-Api-Key", DEVICE_API_KEY);

    Serial.print("POST ");
    Serial.print(url);
    Serial.print(" ");
    Serial.println(body);

    int code = http.POST(body);

    if (code != 200) {
        Serial.print("Backend error, HTTP code: ");
        Serial.println(code);
        res.reason = (code == 401) ? "bad_device_key" : "server_error";
        http.end();
        return res;
    }

    String payload = http.getString();
    http.end();

    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload);
    if (err) {
        Serial.print("Bad JSON from backend: ");
        Serial.println(err.c_str());
        res.reason = "bad_response";
        return res;
    }

    res.networkOk = true;
    res.granted = doc["granted"] | false;
    res.reason = String((const char*)(doc["reason"] | ""));
    res.message = String((const char*)(doc["message"] | ""));
    res.studentName = String((const char*)(doc["student_name"] | ""));
    return res;
}

// ============================================================================
// Gate control
// ============================================================================

// Used for BOTH gates: opens the servo, holds it open for GATE_OPEN_TIME,
// then closes automatically. Simple and identical for entry and exit -
// this is deliberately the least complicated thing that could work, so we
// can confirm the servo + RFID + LED path is solid before layering the
// ultrasonic sensor back into gate timing.
void gateOpen(
    int servoPin,
    int r,
    int g,
    int b
) {
    Serial.println("SERVO -> OPEN");

    setServoAngle(servoPin, SERVO_OPEN);

    delay(200);

    Serial.println("GATE OPEN");

    delay(GATE_OPEN_TIME);

    Serial.println("SERVO -> CLOSED");

    setServoAngle(servoPin, SERVO_CLOSED);

    delay(300);

    Serial.println("GATE CLOSED");

    rgbBlue(r, g, b);
}

void deny(
    int r,
    int g,
    int b
) {
    rgbRed(r, g, b);

    beepError();

    delay(600);

    rgbBlue(r, g, b);
}

// ============================================================================
// Scan processing (identical for entry and exit)
// ============================================================================

void showReady() {
    lcdShow("ATLAS GATE", "READY");
}

void processScan(bool isEntry, const String& uid) {
    const char* direction = isEntry ? "entry" : "exit";
    int r = isEntry ? ENTRY_R : EXIT_R;
    int g = isEntry ? ENTRY_G : EXIT_G;
    int b = isEntry ? ENTRY_B : EXIT_B;
    int servoPin = isEntry ? ENTRY_SERVO_PIN : EXIT_SERVO_PIN;

    Serial.println();
    Serial.println(isEntry ? "========== ENTRY ==========" : "========== EXIT ==========");
    Serial.print("Card UID: ");
    Serial.println(uid);

    lcdShow(isEntry ? "ENTRY GATE" : "EXIT GATE", "VERIFYING...");

    ScanResult res = askBackend(uid, direction);

    // ---- Couldn't reach / trust the backend: stay closed ----
    if (!res.networkOk) {
        Serial.print("FAIL CLOSED: ");
        Serial.println(res.reason);

        if (res.reason == "bad_device_key") {
            lcdShow("CONFIG ERROR", "BAD DEVICE KEY");
        } else if (res.reason == "wifi_down") {
            lcdShow("NO WIFI", "GATE CLOSED");
        } else {
            lcdShow("SERVER OFFLINE", "GATE CLOSED");
        }
        deny(r, g, b);
        delay(1500);
        showReady();
        return;
    }

    // ---- Backend said no ----
    if (!res.granted) {
        Serial.print("DENIED: ");
        Serial.println(res.reason);

        lcdShow(res.studentName.length() ? res.studentName : String("ACCESS DENIED"),
                res.message.length() ? res.message : res.reason);
        deny(r, g, b);
        delay(1000);
        showReady();
        return;
    }

    // ---- Granted: open NOW. The backend logs to the blockchain on its own
    // in the background, so the gate never waits on the chain. ----
    Serial.println(isEntry ? "ENTRY GRANTED" : "EXIT GRANTED");

    lcdShow(res.studentName, res.message);
    rgbGreen(r, g, b);
    beepSuccess();

    gateOpen(servoPin, r, g, b);

    lcdShow(res.studentName, isEntry ? "INSIDE" : "OUTSIDE");
    delay(1000);
    showReady();
}

// ============================================================================
// Idle-state presence display
// ============================================================================

// While nothing else is happening, periodically checks the ultrasonic sensor
// and updates the LCD to nudge someone standing at the gate to scan their
// card. This does not gate access by itself — RFID is still required — it's
// just a presence-aware idle screen.
void updateIdlePresenceDisplay() {
    static unsigned long lastCheck = 0;
    static bool wasPresent = false;

    unsigned long now = millis();

    if (now - lastCheck < PRESENCE_POLL_INTERVAL) {
        return;
    }

    lastCheck = now;

    long distance = readUltrasonicCM();
    bool isPresent = (distance > 0 && distance < PRESENCE_CM);

    if (isPresent != wasPresent) {
        wasPresent = isPresent;

        if (isPresent) {
            Serial.println("Presence detected at entry gate");

            lcdShow(
                "ATLAS GATE",
                "APPROACH: SCAN"
            );
        } else {
            lcdShow(
                "ATLAS GATE",
                "READY"
            );
        }
    }
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup() {

    Serial.begin(115200);

    delay(500);

    Wire.begin(
        LCD_SDA,
        LCD_SCL
    );

    lcd.init();
    lcd.backlight();

    lcdShow(
        "ATLAS GATE",
        "STARTING..."
    );

    pinMode(ENTRY_R, OUTPUT);
    pinMode(ENTRY_G, OUTPUT);
    pinMode(ENTRY_B, OUTPUT);

    pinMode(EXIT_R, OUTPUT);
    pinMode(EXIT_G, OUTPUT);
    pinMode(EXIT_B, OUTPUT);

    pinMode(BUZZER_PIN, OUTPUT);

    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    rgbBlue(
        ENTRY_R,
        ENTRY_G,
        ENTRY_B
    );

    rgbBlue(
        EXIT_R,
        EXIT_G,
        EXIT_B
    );

    SPI.begin(
        SPI_SCK,
        SPI_MISO,
        SPI_MOSI
    );

    pinMode(ENTRY_SS, OUTPUT);
    pinMode(EXIT_SS, OUTPUT);

    digitalWrite(ENTRY_SS, HIGH);
    digitalWrite(EXIT_SS, HIGH);

    entryReader.PCD_Init();
    delay(50);

    exitReader.PCD_Init();
    delay(50);

    // Servo pins are attached directly to the LEDC peripheral (see
    // attachServoPin() / setServoAngle() above) instead of going through
    // the ESP32Servo library, which didn't resolve the issue across three
    // attempts and is the more likely source of the incompatibility.

    attachServoPin(ENTRY_SERVO_PIN, ENTRY_SERVO_LEDC_CHANNEL);
    setServoAngle(ENTRY_SERVO_PIN, SERVO_CLOSED);

    attachServoPin(EXIT_SERVO_PIN, EXIT_SERVO_LEDC_CHANNEL);
    setServoAngle(EXIT_SERVO_PIN, SERVO_CLOSED);

    Serial.println();
    Serial.println("==============================");
    Serial.println("      ATLAS GATE (integrated)");
    Serial.println("  RFID + ULTRASONIC + BACKEND");
    Serial.println("==============================");

    Serial.println("ENTRY SERVO      = GPIO 25");
    Serial.println("EXIT SERVO       = GPIO 33");
    Serial.println("ULTRASONIC TRIG  = GPIO 15");
    Serial.println("ULTRASONIC ECHO  = GPIO 34");

#if ATLAS_LEDC_NEW_API
    Serial.println("LEDC API detected: NEW (pin-based, core 3.x+)");
#else
    Serial.println("LEDC API detected: OLD (channel-based, core < 3.x)");
#endif

    // ---------------------------------------------------------------
    // SERVO SELF-TEST
    // Runs automatically on every boot, with zero dependency on RFID,
    // verification, or the ultrasonic sensor. If the horns visibly sweep
    // here, the wiring + LEDC attach are fine and the problem is elsewhere
    // in the logic. If they DON'T move here, it's a wiring/pin issue,
    // not a logic issue - check the diagram connections next.
    // ---------------------------------------------------------------
    Serial.println();
    Serial.println("SERVO SELF-TEST: sweeping both servos 0 -> 90 -> 0");

    setServoAngle(ENTRY_SERVO_PIN, SERVO_OPEN);
    setServoAngle(EXIT_SERVO_PIN, SERVO_OPEN);
    Serial.println("SELF-TEST: both servos -> 90 (should be visibly open now)");
    delay(1500);

    setServoAngle(ENTRY_SERVO_PIN, SERVO_CLOSED);
    setServoAngle(EXIT_SERVO_PIN, SERVO_CLOSED);
    Serial.println("SELF-TEST: both servos -> 0 (should be visibly closed now)");
    delay(1000);

    Serial.println("SERVO SELF-TEST complete.");
    Serial.println();

    // ---- WiFi ----
    lcdShow("CONNECTING WIFI", WIFI_SSID);
    Serial.print("Connecting to WiFi: ");
    Serial.println(WIFI_SSID);
    if (connectWiFi(15000)) {
        Serial.print("WiFi OK, IP: ");
        Serial.println(WiFi.localIP());
        Serial.print("Backend: http://");
        Serial.print(BACKEND_HOST);
        Serial.print(":");
        Serial.println(BACKEND_PORT);
        lcdShow("WIFI OK", WiFi.localIP().toString());
        delay(1200);
    } else {
        Serial.println("WiFi FAILED - will keep retrying on each scan. Gate fails closed.");
        lcdShow("WIFI FAILED", "CHECK config.h");
        delay(2000);
    }

    Serial.println("System ready.");

    delay(300);

    lcdShow(
        "ATLAS GATE",
        "READY"
    );
}

void loop() {

    String uid;

    if (
        readCard(
            entryReader,
            ENTRY_SS,
            EXIT_SS,
            uid
        )
    ) {
        processScan(true, uid);
        delay(500);
    }

    if (
        readCard(
            exitReader,
            EXIT_SS,
            ENTRY_SS,
            uid
        )
    ) {
        processScan(false, uid);
        delay(500);
    }

    updateIdlePresenceDisplay();

    // Live distance readout, printed a few times a second. In Wokwi, click
    // the HC-SR04 part while the simulation is running - it opens a distance
    // slider. Drag it and watch these numbers change here in the Serial
    // Monitor. Without touching that slider, the sensor reports a fixed
    // value forever (whatever "distance" is set to in diagram.json), which
    // is why the gate/LED can look "stuck" - it's waiting on a signal that
    // never arrives until you move the slider yourself.
    static unsigned long lastDistancePrint = 0;
    if (millis() - lastDistancePrint > 500) {
        lastDistancePrint = millis();

        long d = readUltrasonicCM();

        Serial.print("Ultrasonic distance: ");
        if (d < 0) {
            Serial.println("no echo");
        } else {
            Serial.print(d);
            Serial.println(" cm");
        }
    }

    delay(10);
}
