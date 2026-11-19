#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>
#include <LiquidCrystal_I2C.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

// ---- Run modes (set ATLAS_MODE in config.h; default = real hardware) ----
//  MODE_REAL_HARDWARE : real ESP32 on your WiFi, talks to the backend on your laptop's LAN IP.
//  MODE_WOKWI_TUNNEL  : Wokwi simulator. Sim WiFi is only "Wokwi-GUEST" and cannot see your
//                       laptop, so the backend is reached through a public HTTPS tunnel.
//  MODE_OFFLINE_DEMO  : no network at all. 3 built-in test cards decide locally. For testing
//                       the gate hardware logic (servos, LEDs, LCD, buzzer) in the simulator.
#define MODE_REAL_HARDWARE 0
#define MODE_WOKWI_TUNNEL 1
#define MODE_OFFLINE_DEMO 2

#include "config.h"

#ifndef ATLAS_MODE
#define ATLAS_MODE MODE_REAL_HARDWARE
#endif
#ifndef TUNNEL_HOST
#define TUNNEL_HOST "your-name.trycloudflare.com"
#endif

#if ATLAS_MODE == MODE_WOKWI_TUNNEL
#define NET_SSID "Wokwi-GUEST" // the ONLY network that exists in the simulator
#define NET_PASSWORD ""
#define NET_CHANNEL 6 // skips the scan, saves ~4 s
#define NET_HOST TUNNEL_HOST
#define NET_PORT 443
#define NET_HTTPS 1
#define NET_TIMEOUT_MS 15000 // TLS handshake in the sim is slow
#else
#define NET_SSID WIFI_SSID
#define NET_PASSWORD WIFI_PASSWORD
#define NET_CHANNEL 0
#define NET_HOST BACKEND_HOST
#define NET_PORT BACKEND_PORT
#define NET_HTTPS 0
#define NET_TIMEOUT_MS HTTP_TIMEOUT_MS
#endif

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

const int SERVO_PWM_FREQ = 50; // standard hobby servo signal frequency
const int SERVO_PWM_RES = 12;  // resolution bits -> duty range 0-4095
const int SERVO_MIN_US = 500;  // pulse width (microseconds) at 0 degrees
const int SERVO_MAX_US = 2400; // pulse width (microseconds) at 180 degrees

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

void rgbOff(int r, int g, int b)
{
    digitalWrite(r, LOW);
    digitalWrite(g, LOW);
    digitalWrite(b, LOW);
}

void rgbRed(int r, int g, int b)
{
    rgbOff(r, g, b);
    digitalWrite(r, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(r);
    Serial.println(" set -> RED");
}

void rgbGreen(int r, int g, int b)
{
    rgbOff(r, g, b);
    digitalWrite(g, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(g);
    Serial.println(" set -> GREEN");
}

void rgbBlue(int r, int g, int b)
{
    rgbOff(r, g, b);
    digitalWrite(b, HIGH);
    Serial.print("[LED] pin ");
    Serial.print(b);
    Serial.println(" set -> BLUE (idle)");
}

void lcdShow(String line1, String line2)
{
    lcd.clear();

    lcd.setCursor(0, 0);
    lcd.print(line1.substring(0, 16));

    lcd.setCursor(0, 1);
    lcd.print(line2.substring(0, 16));
}

String getUID(MFRC522 &reader)
{
    String uid = "";

    for (byte i = 0; i < reader.uid.size; i++)
    {
        if (reader.uid.uidByte[i] < 0x10)
        {
            uid += "0";
        }

        uid += String(reader.uid.uidByte[i], HEX);
    }

    uid.toUpperCase();
    return uid;
}

bool readCard(
    MFRC522 &reader,
    int thisSS,
    int otherSS,
    String &uid)
{
    digitalWrite(otherSS, HIGH);
    digitalWrite(thisSS, HIGH);

    if (!reader.PICC_IsNewCardPresent())
    {
        return false;
    }

    if (!reader.PICC_ReadCardSerial())
    {
        return false;
    }

    uid = getUID(reader);

    reader.PICC_HaltA();
    reader.PCD_StopCrypto1();

    digitalWrite(thisSS, HIGH);

    return true;
}

// BUZZER ON ITS OWN LEDC CHANNEL.
// Do NOT use Arduino's tone() here: on ESP32 core 2.x it always grabs LEDC
// channel 0 -- the entry servo's channel -- and channels 0/1 share a hardware
// timer, so the first beep re-clocks BOTH servos to the buzzer frequency and
// they stop working after that (boot self-test passes, real scans don't).
// Channel 4 sits on timer 2, away from the servos on timer 0.
const int BUZZER_LEDC_CHANNEL = 4;

void buzzerInit()
{
#if ATLAS_LEDC_NEW_API
    ledcAttach(BUZZER_PIN, 2000, 8);
    ledcWriteTone(BUZZER_PIN, 0);
#else
    ledcSetup(BUZZER_LEDC_CHANNEL, 2000, 8);
    ledcAttachPin(BUZZER_PIN, BUZZER_LEDC_CHANNEL);
    ledcWriteTone(BUZZER_LEDC_CHANNEL, 0);
#endif
}

void buzz(unsigned freq, unsigned ms)
{
#if ATLAS_LEDC_NEW_API
    ledcWriteTone(BUZZER_PIN, freq);
    delay(ms);
    ledcWriteTone(BUZZER_PIN, 0);
#else
    ledcWriteTone(BUZZER_LEDC_CHANNEL, freq);
    delay(ms);
    ledcWriteTone(BUZZER_LEDC_CHANNEL, 0);
#endif
}

void beepSuccess() { buzz(1800, 150); }
void beepError() { buzz(400, 300); }

// ============================================================================
// Servo control (direct LEDC, no ESP32Servo library)
// ============================================================================

// Moves the servo on the given pin to the given angle (0-180) by computing
// the correct PWM duty cycle ourselves and writing it straight to the
// ESP32's LEDC peripheral. Built into the ESP32 Arduino core itself - no
// external servo library required.
void setServoAngle(int pin, int angle)
{
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
void attachServoPin(int pin, int channel)
{
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
long readUltrasonicCM()
{
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);
    delayMicroseconds(2);

    digitalWrite(ULTRASONIC_TRIG_PIN, HIGH);
    delayMicroseconds(10);

    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    // 30ms timeout ~= 5m max range, plenty for a gate/doorway sensor.
    long duration = pulseIn(ULTRASONIC_ECHO_PIN, HIGH, 30000UL);

    if (duration == 0)
    {
        return -1;
    }

    long distanceCm = duration * 0.0343 / 2;
    return distanceCm;
}

// ============================================================================
// WiFi + backend communication
// ============================================================================

bool wifiConnected()
{
    return WiFi.status() == WL_CONNECTED;
}

// Blocks up to timeoutMs waiting for WiFi. Used at boot and before a scan
// if the link dropped.
bool connectWiFi(unsigned long timeoutMs)
{
    if (wifiConnected())
        return true;

    WiFi.mode(WIFI_STA);
#if NET_CHANNEL > 0
    WiFi.begin(NET_SSID, NET_PASSWORD, NET_CHANNEL);
#else
    WiFi.begin(NET_SSID, NET_PASSWORD);
#endif

    unsigned long start = millis();
    while (!wifiConnected() && millis() - start < timeoutMs)
    {
        delay(250);
        Serial.print(".");
    }
    Serial.println();
    return wifiConnected();
}

// Called when WiFi fails at boot: says WHY, and lists the networks the ESP32
// can actually see so you can spot a wrong / invisible SSID (curly apostrophe,
// 5 GHz-only hotspot, out of range...).
void wifiDiagnose()
{
    wl_status_t st = WiFi.status();
    Serial.print("WiFi status code ");
    Serial.print((int)st);
    Serial.print(" = ");
    switch (st)
    {
    case WL_NO_SSID_AVAIL:
        Serial.println("SSID NOT FOUND (name wrong, out of range, or 5 GHz only)");
        break;
    case WL_CONNECT_FAILED:
        Serial.println("CONNECT FAILED (wrong password?)");
        break;
    case WL_DISCONNECTED:
        Serial.println("DISCONNECTED (wrong password, or AP refused)");
        break;
    default:
        Serial.println("other");
        break;
    }
    Serial.print("Looking for SSID: [");
    Serial.print(NET_SSID);
    Serial.println("]");
    Serial.println("Networks this ESP32 can see:");
    int n = WiFi.scanNetworks();
    if (n <= 0)
        Serial.println("  (none -- radio problem, or no 2.4 GHz network in range)");
    for (int i = 0; i < n && i < 15; i++)
    {
        Serial.print("  [");
        Serial.print(WiFi.SSID(i));
        Serial.print("]  ch ");
        Serial.print(WiFi.channel(i));
        Serial.print("  ");
        Serial.print(WiFi.RSSI(i));
        Serial.println(" dBm");
    }
}

#if ATLAS_MODE == MODE_OFFLINE_DEMO
// Offline demo: mirrors the backend's entry/exit rules with the 3 seed cards.
struct DemoStudent
{
    const char *uid;
    const char *name;
    bool inside;
};
DemoStudent demoStudents[] = {
    {"01020304", "Rishit", false},
    {"11223344", "Student2", false},
    {"55667788", "Student3", false}};
#endif

struct ScanResult
{
    bool networkOk; // false => couldn't get a valid answer from the backend
    bool granted;
    String reason;
    String message; // short text from the backend, e.g. "Entry granted"
    String studentName;
};

#if ATLAS_MODE == MODE_OFFLINE_DEMO
struct ScanResult demoDecide(const String &uid, const char *direction)
{
    ScanResult res = {true, false, "", "", ""};
    delay(300); // pretend network latency
    bool isEntry = (strcmp(direction, "entry") == 0);
    for (auto &s : demoStudents)
    {
        if (!uid.equalsIgnoreCase(s.uid))
            continue;
        res.studentName = s.name;
        if (isEntry && s.inside)
        {
            res.reason = "already_inside";
            res.message = "Already inside";
            return res;
        }
        if (!isEntry && !s.inside)
        {
            res.reason = "already_outside";
            res.message = "Already outside";
            return res;
        }
        s.inside = isEntry;
        res.granted = true;
        res.reason = "granted";
        res.message = isEntry ? "Entry granted" : "Exit granted";
        return res;
    }
    res.reason = "unknown_card";
    res.message = "Unknown card";
    return res;
}
#endif

// GET /health -> returns the HTTP status code (200 = backend reachable), or <=0 on failure.
int backendHealth()
{
    String url = String(NET_HTTPS ? "https://" : "http://") + NET_HOST + ":" + NET_PORT + "/health";
#if NET_HTTPS
    WiFiClientSecure secureClient;
    secureClient.setInsecure();
#endif
    HTTPClient http;
    http.setTimeout(NET_TIMEOUT_MS);
#if NET_HTTPS
    http.begin(secureClient, url);
#else
    http.begin(url);
#endif
    int code = http.GET();
    http.end();
    return code;
}

// Asks the backend whether this card may pass. FAILS CLOSED: any network,
// HTTP or parsing problem returns networkOk=false, granted=false.
ScanResult askBackend(const String &uid, const char *direction)
{
    ScanResult res = {false, false, "", "", ""};

#if ATLAS_MODE == MODE_OFFLINE_DEMO
    return demoDecide(uid, direction);
#endif

    if (!wifiConnected())
    {
        Serial.println("WiFi down, trying to reconnect...");
        WiFi.disconnect();
        if (!connectWiFi(5000))
        {
            res.reason = "wifi_down";
            return res;
        }
    }

    String url = String(NET_HTTPS ? "https://" : "http://") + NET_HOST + ":" + NET_PORT + "/gate/scan";

    JsonDocument req;
    req["uid"] = uid;
    req["direction"] = direction;
    String body;
    serializeJson(req, body);

#if NET_HTTPS
    WiFiClientSecure secureClient; // declared BEFORE http so it outlives it
    secureClient.setInsecure();    // dev/tunnel only: skips certificate checks
#endif
    HTTPClient http;
    http.setTimeout(NET_TIMEOUT_MS);
#if NET_HTTPS
    http.begin(secureClient, url);
#else
    http.begin(url);
#endif
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Device-Api-Key", DEVICE_API_KEY);

    Serial.print("POST ");
    Serial.print(url);
    Serial.print(" ");
    Serial.println(body);

    int code = http.POST(body);

    if (code != 200)
    {
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
    if (err)
    {
        Serial.print("Bad JSON from backend: ");
        Serial.println(err.c_str());
        res.reason = "bad_response";
        return res;
    }

    res.networkOk = true;
    res.granted = doc["granted"] | false;
    res.reason = String((const char *)(doc["reason"] | ""));
    res.message = String((const char *)(doc["message"] | ""));
    res.studentName = String((const char *)(doc["student_name"] | ""));
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
    int b)
{
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
    int b)
{
    rgbRed(r, g, b);

    beepError();

    delay(600);

    rgbBlue(r, g, b);
}

// ============================================================================
// Scan processing (identical for entry and exit)
// ============================================================================

void showReady()
{
    lcdShow("ATLAS GATE", "READY");
}

void processScan(bool isEntry, const String &uid)
{
    const char *direction = isEntry ? "entry" : "exit";
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
    if (!res.networkOk)
    {
        Serial.print("FAIL CLOSED: ");
        Serial.println(res.reason);

        if (res.reason == "bad_device_key")
        {
            lcdShow("CONFIG ERROR", "BAD DEVICE KEY");
        }
        else if (res.reason == "wifi_down")
        {
            lcdShow("NO WIFI", "GATE CLOSED");
        }
        else
        {
            lcdShow("SERVER OFFLINE", "GATE CLOSED");
        }
        deny(r, g, b);
        delay(1500);
        showReady();
        return;
    }

    // ---- Backend said no ----
    if (!res.granted)
    {
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
void updateIdlePresenceDisplay()
{
    static unsigned long lastCheck = 0;
    static bool wasPresent = false;

    unsigned long now = millis();

    if (now - lastCheck < PRESENCE_POLL_INTERVAL)
    {
        return;
    }

    lastCheck = now;

    long distance = readUltrasonicCM();
    bool isPresent = (distance > 0 && distance < PRESENCE_CM);

    if (isPresent != wasPresent)
    {
        wasPresent = isPresent;

        if (isPresent)
        {
            Serial.println("Presence detected at entry gate");

            lcdShow(
                "ATLAS GATE",
                "APPROACH: SCAN");
        }
        else
        {
            lcdShow(
                "ATLAS GATE",
                "READY");
        }
    }
}

// ============================================================================
// Setup / loop
// ============================================================================

void setup()
{

    Serial.begin(115200);

    delay(500);

    Wire.begin(
        LCD_SDA,
        LCD_SCL);

    lcd.init();
    lcd.backlight();

    lcdShow(
        "ATLAS GATE",
        "STARTING...");

    pinMode(ENTRY_R, OUTPUT);
    pinMode(ENTRY_G, OUTPUT);
    pinMode(ENTRY_B, OUTPUT);

    pinMode(EXIT_R, OUTPUT);
    pinMode(EXIT_G, OUTPUT);
    pinMode(EXIT_B, OUTPUT);

    buzzerInit();

    pinMode(ULTRASONIC_TRIG_PIN, OUTPUT);
    pinMode(ULTRASONIC_ECHO_PIN, INPUT);
    digitalWrite(ULTRASONIC_TRIG_PIN, LOW);

    rgbBlue(
        ENTRY_R,
        ENTRY_G,
        ENTRY_B);

    rgbBlue(
        EXIT_R,
        EXIT_G,
        EXIT_B);

    SPI.begin(
        SPI_SCK,
        SPI_MISO,
        SPI_MOSI);

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

#if ATLAS_MODE == MODE_OFFLINE_DEMO
    Serial.println("MODE: OFFLINE DEMO (no WiFi). Cards 01020304 / 11223344 / 55667788 are built in.");
    lcdShow("OFFLINE DEMO", "NO NETWORK");
    delay(1200);
#else
    // ---- WiFi ----
#if ATLAS_MODE == MODE_WOKWI_TUNNEL
    Serial.println("MODE: WOKWI + TUNNEL");
#else
    Serial.println("MODE: REAL HARDWARE");
#endif
    lcdShow("CONNECTING WIFI", NET_SSID);
    Serial.print("Connecting to WiFi: [");
    Serial.print(NET_SSID);
    Serial.println("]");
    if (connectWiFi(15000))
    {
        Serial.print("WiFi OK, ESP32 IP: ");
        Serial.println(WiFi.localIP());
        Serial.print("Backend: ");
        Serial.print(NET_HTTPS ? "https://" : "http://");
        Serial.print(NET_HOST);
        Serial.print(":");
        Serial.println(NET_PORT);
        lcdShow("WIFI OK", WiFi.localIP().toString());
        delay(1200);

        lcdShow("CHECKING SERVER", "...");
        int code = backendHealth();
        Serial.print("Backend /health -> HTTP ");
        Serial.println(code);
        if (code == 200)
        {
            lcdShow("BACKEND OK", "READY");
        }
        else
        {
            Serial.println("Backend NOT reachable. Check: uvicorn --host 0.0.0.0, same WiFi, firewall, BACKEND_HOST IP.");
            lcdShow("BACKEND DOWN", String("code ") + code);
        }
        delay(1500);
    }
    else
    {
        Serial.println("WiFi FAILED - will keep retrying on each scan. Gate fails closed.");
        wifiDiagnose();
        lcdShow("WIFI FAILED", "SEE SERIAL LOG");
        delay(2500);
    }
#endif

    Serial.println("System ready.");

    delay(300);

    lcdShow(
        "ATLAS GATE",
        "READY");
}

void loop()
{

    String uid;

    if (
        readCard(
            entryReader,
            ENTRY_SS,
            EXIT_SS,
            uid))
    {
        processScan(true, uid);
        delay(500);
    }

    if (
        readCard(
            exitReader,
            EXIT_SS,
            ENTRY_SS,
            uid))
    {
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
    if (millis() - lastDistancePrint > 500)
    {
        lastDistancePrint = millis();

        long d = readUltrasonicCM();

        Serial.print("Ultrasonic distance: ");
        if (d < 0)
        {
            Serial.println("no echo");
        }
        else
        {
            Serial.print(d);
            Serial.println(" cm");
        }
    }

    delay(10);
}
