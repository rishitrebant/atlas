#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <MFRC522.h>
#include <ESP32Servo.h>
#include <LiquidCrystal_I2C.h>

#define SPI_SCK 18
#define SPI_MISO 19
#define SPI_MOSI 23

#define ENTRY_SS 5
#define ENTRY_RST 21

#define EXIT_SS 27
#define EXIT_RST 22

MFRC522 entryReader(ENTRY_SS, ENTRY_RST);
MFRC522 exitReader(EXIT_SS, EXIT_RST);

#define LCD_SDA 16
#define LCD_SCL 17

LiquidCrystal_I2C lcd(0x27, 16, 2);

#define ENTRY_R 12
#define ENTRY_G 13
#define ENTRY_B 26

#define EXIT_R 14
#define EXIT_G 4
#define EXIT_B 2

#define ENTRY_SERVO_PIN 25
#define EXIT_SERVO_PIN 33

#define BUZZER_PIN 32

Servo entryServo;
Servo exitServo;

const int SERVO_CLOSED = 0;
const int SERVO_OPEN = 90;

const unsigned long GATE_OPEN_TIME = 7000;

struct Student {
    const char* id;
    const char* name;
    String uid;
    bool inside;
};

Student students[] = {
    {"ATLAS001", "Rishit",   "01020304", false},
    {"ATLAS002", "Student2", "11223344", false},
    {"ATLAS003", "Student3", "55667788", false}
};

const int STUDENT_COUNT =
    sizeof(students) / sizeof(students[0]);

void rgbOff(int r, int g, int b) {
    digitalWrite(r, LOW);
    digitalWrite(g, LOW);
    digitalWrite(b, LOW);
}

void rgbRed(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(r, HIGH);
}

void rgbGreen(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(g, HIGH);
}

void rgbBlue(int r, int g, int b) {
    rgbOff(r, g, b);
    digitalWrite(b, HIGH);
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

int findStudent(String uid) {
    uid.toUpperCase();

    for (int i = 0; i < STUDENT_COUNT; i++) {
        if (students[i].uid == uid) {
            return i;
        }
    }

    return -1;
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

void gateOpenFor7Seconds(
    Servo& servo,
    int r,
    int g,
    int b
) {
    Serial.println("SERVO -> OPEN");

    servo.write(SERVO_OPEN);

    delay(200);

    Serial.println("GATE OPEN");

    delay(GATE_OPEN_TIME);

    Serial.println("SERVO -> CLOSED");

    servo.write(SERVO_CLOSED);

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

void processEntry(String uid) {

    Serial.println();
    Serial.println("========== ENTRY ==========");

    lcdShow(
        "ENTRY GATE",
        "SCANNING..."
    );

    int index = findStudent(uid);

    if (index == -1) {

        Serial.println("UNKNOWN CARD");

        lcdShow(
            "UNKNOWN CARD",
            "ENTRY DENIED"
        );

        deny(
            ENTRY_R,
            ENTRY_G,
            ENTRY_B
        );

        delay(800);

        lcdShow(
            "ATLAS GATE",
            "READY"
        );

        return;
    }

    Student& student = students[index];

    Serial.print("Student: ");
    Serial.println(student.name);

    if (student.inside) {

        Serial.println("ALREADY INSIDE");

        lcdShow(
            student.name,
            "ALREADY INSIDE"
        );

        deny(
            ENTRY_R,
            ENTRY_G,
            ENTRY_B
        );

        delay(800);

        lcdShow(
            "ATLAS GATE",
            "READY"
        );

        return;
    }

    student.inside = true;

    Serial.println("ENTRY GRANTED");

    lcdShow(
        student.name,
        "ENTRY GRANTED"
    );

    rgbGreen(
        ENTRY_R,
        ENTRY_G,
        ENTRY_B
    );

    beepSuccess();

    gateOpenFor7Seconds(
        entryServo,
        ENTRY_R,
        ENTRY_G,
        ENTRY_B
    );

    lcdShow(
        student.name,
        "INSIDE"
    );

    delay(1000);

    lcdShow(
        "ATLAS GATE",
        "READY"
    );
}

void processExit(String uid) {

    Serial.println();
    Serial.println("========== EXIT ==========");

    lcdShow(
        "EXIT GATE",
        "SCANNING..."
    );

    int index = findStudent(uid);

    if (index == -1) {

        Serial.println("UNKNOWN CARD");

        lcdShow(
            "UNKNOWN CARD",
            "EXIT DENIED"
        );

        deny(
            EXIT_R,
            EXIT_G,
            EXIT_B
        );

        delay(800);

        lcdShow(
            "ATLAS GATE",
            "READY"
        );

        return;
    }

    Student& student = students[index];

    Serial.print("Student: ");
    Serial.println(student.name);

    if (!student.inside) {

        Serial.println("ALREADY OUTSIDE");

        lcdShow(
            student.name,
            "ALREADY OUTSIDE"
        );

        deny(
            EXIT_R,
            EXIT_G,
            EXIT_B
        );

        delay(800);

        lcdShow(
            "ATLAS GATE",
            "READY"
        );

        return;
    }

    student.inside = false;

    Serial.println("EXIT GRANTED");

    lcdShow(
        student.name,
        "EXIT GRANTED"
    );

    rgbGreen(
        EXIT_R,
        EXIT_G,
        EXIT_B
    );

    beepSuccess();

    gateOpenFor7Seconds(
        exitServo,
        EXIT_R,
        EXIT_G,
        EXIT_B
    );

    lcdShow(
        student.name,
        "OUTSIDE"
    );

    delay(1000);

    lcdShow(
        "ATLAS GATE",
        "READY"
    );
}

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

    entryServo.setPeriodHertz(50);

    entryServo.attach(
        ENTRY_SERVO_PIN,
        500,
        2400
    );

    entryServo.write(
        SERVO_CLOSED
    );

    exitServo.setPeriodHertz(50);

    exitServo.attach(
        EXIT_SERVO_PIN,
        500,
        2400
    );

    exitServo.write(
        SERVO_CLOSED
    );

    Serial.println();
    Serial.println("==============================");
    Serial.println("      ATLAS MILESTONE 2");
    Serial.println("     RFID GATE SIMULATION");
    Serial.println("==============================");

    Serial.println("ENTRY SERVO = GPIO 25");
    Serial.println("EXIT SERVO  = GPIO 33");

    Serial.println("System ready.");

    delay(1000);

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
        processEntry(uid);
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
        processExit(uid);
        delay(500);
    }

    delay(10);
}