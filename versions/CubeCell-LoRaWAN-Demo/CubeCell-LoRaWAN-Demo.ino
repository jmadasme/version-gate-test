/*
 * CubeCell-LoRaWAN-Demo.ino — Nodo LoRaWAN aislado (demo)
 * ========================================================
 * Heltec CubeCell HTCC-AB01 (ASR6502 + SX1262)
 * Region: AU915 sub-banda 2 | OTAA Clase A | RadioLib 7.7.1
 * Serial: 9600 8N1
 *
 * DEMO AUTONOMA DE LORAWAN (sin puente ESP-NOW):
 *   - Se une a la red (OTAA) y PERSISTE la sesion en flash
 *     (no re-enrola en cada arranque).
 *   - Heartbeat cada 30 s (payload 0xBB) que abre la ventana RX.
 *   - Si el gateway envia un downlink, se muestra en el serial
 *     como [DOWNLINK] XX XX → "texto".
 *   - Modo manual: escribir HEX + Enter en el serial → uplink.
 *   - Comando ERASE: borra la sesion persistida y reinicia
 *     (util si el NS fue reiniciado y hay conflicto de JoinNonce).
 *
 * USO:
 *   1. Registra el dispositivo en el gateway (DevEUI/JoinEUI/AppKey
 *      en credentials.h).
 *   2. Abre el monitor serial a 9600.
 *   3. Veras el join, el heartbeat cada 30s, y los downlinks.
 *   4. Para probar un uplink manual, escribe HEX + Enter (ej: DE AD BE EF).
 */

#include <RadioLib.h>
#include "credentials.h"

// Acceso a la flash para persistir la sesion
extern "C" {
#include "hal/soc/flash.h"
void board_init(void);   // inicializa la tabla de particiones
}

#define debug(fmt, ...) Serial.printf(fmt, ##__VA_ARGS__)

/* ===================================================================
 *  RADIO SX1262 (pines internos del CubeCell)
 * =================================================================== */
Module mod(35, 38, 47, 39);   // NSS, DIO1, RST, BUSY
SX1262 radio(&mod);

const LoRaWANBand_t Region = AU915;
const uint8_t subBand = 2;
LoRaWANNode node(&radio, &Region, subBand);

/* ===================================================================
 *  BUFFERS Y CONSTANTES
 * =================================================================== */
#define MAX_PAYLOAD     51
#define HEARTBEAT_MS    30000UL   // heartbeat cada 30 s
#define SERIAL_BUF      256

uint8_t  downlinkData[MAX_PAYLOAD];
size_t   downlinkLen = 0;
uint32_t lastUplinkMs = 0;

uint8_t  txBuffer[MAX_PAYLOAD];
size_t   txLen = 0;
char     serialLine[SERIAL_BUF];
size_t   serialPos = 0;

const uint8_t heartbeatPayload[] = { 0xBB };
const size_t  heartbeatLen = 1;

/* ===================================================================
 *  PERSISTENCIA DE SESION (evita re-join en cada arranque)
 * =================================================================== */
#define SESSION_PARTITION HAL_PARTITION_PARAMETER_1
static uint8_t persistSession[RADIOLIB_LORAWAN_SESSION_BUF_SIZE];
static uint8_t persistNonces[RADIOLIB_LORAWAN_NONCES_BUF_SIZE];

/* ===================================================================
 *  WORKAROUND ASR6502: sleep basado en millis() (timer bug)
 * =================================================================== */
static void radioSleepDelay(RadioLibTime_t ms) {
    if (ms == 0) return;
    uint32_t start = millis();
    while ((millis() - start) < ms) { /* NOP */ }
}

/* ===================================================================
 *  DIAGNOSTICO
 * =================================================================== */
static const char* stateDecode(int16_t s) {
    switch (s) {
        case RADIOLIB_ERR_NONE:                return "OK";
        case RADIOLIB_ERR_CHIP_NOT_FOUND:      return "CHIP_NOT_FOUND";
        case RADIOLIB_ERR_RX_TIMEOUT:          return "RX_TIMEOUT";
        case RADIOLIB_ERR_NETWORK_NOT_JOINED:  return "NOT_JOINED";
        case RADIOLIB_ERR_NO_JOIN_ACCEPT:      return "NO_JOIN_ACCEPT";
        case RADIOLIB_ERR_JOIN_NONCE_INVALID:  return "JOIN_NONCE_INVALID";
        case RADIOLIB_LORAWAN_NEW_SESSION:     return "NEW_SESSION";
        case RADIOLIB_LORAWAN_SESSION_RESTORED: return "SESSION_RESTORED";
        default:                               return "UNKNOWN";
    }
}

/* ===================================================================
 *  PERSISTENCIA: guardar / cargar la sesion
 * =================================================================== */
static void saveSession(void) {
    uint8_t* s = node.getBufferSession();
    uint8_t* n = node.getBufferNonces();
    uint32_t off = 0;
    hal_flash_erase(SESSION_PARTITION, 0, 4096);
    off = 0;
    hal_flash_write(SESSION_PARTITION, &off, s, RADIOLIB_LORAWAN_SESSION_BUF_SIZE);
    hal_flash_write(SESSION_PARTITION, &off, n, RADIOLIB_LORAWAN_NONCES_BUF_SIZE);
    debug("[PERSIST] Sesion guardada en flash\n");
}

static void loadSession(void) {
    uint32_t off = 0;
    hal_flash_read(SESSION_PARTITION, &off, persistSession, RADIOLIB_LORAWAN_SESSION_BUF_SIZE);
    hal_flash_read(SESSION_PARTITION, &off, persistNonces, RADIOLIB_LORAWAN_NONCES_BUF_SIZE);
    // Orden importante: primero nonces, luego sesion
    node.setBufferNonces(persistNonces);
    node.setBufferSession(persistSession);
}

/* ===================================================================
 *  REINTENTAR JOIN
 * =================================================================== */
static bool ensureJoined(void) {
    if (node.isActivated()) return true;
    debug("[REJOIN] Intentando...\n");
    int state = node.activateOTAA();
    if (state == RADIOLIB_LORAWAN_NEW_SESSION) {
        debug("[REJOIN] +++ EXITOSO +++\n");
        saveSession();
        return true;
    }
    if (state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("[REJOIN] +++ SESION RESTAURADA +++\n");
        return true;
    }
    debug("[REJOIN] Fallo: %d (%s)\n", state, stateDecode(state));
    return false;
}

/* ===================================================================
 *  PARSER HEX: "DE AD BE EF" o "DEADBEEF" → bytes
 * =================================================================== */
static size_t parseHexString(const char* input, uint8_t* output, size_t maxOut) {
    size_t outLen = 0;
    char clean[256];
    size_t cleanLen = 0;
    for (size_t i = 0; input[i] != '\0' && cleanLen < sizeof(clean) - 1; i++) {
        char c = input[i];
        if ((c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') || (c >= 'a' && c <= 'f')) {
            clean[cleanLen++] = c;
        }
    }
    clean[cleanLen] = '\0';
    if (cleanLen == 0 || cleanLen % 2 != 0) return 0;
    for (size_t i = 0; i < cleanLen && outLen < maxOut; i += 2) {
        char byteStr[3] = { clean[i], clean[i + 1], '\0' };
        output[outLen++] = (uint8_t)strtoul(byteStr, NULL, 16);
    }
    return outLen;
}

/* ===================================================================
 *  MOSTRAR DOWNLINK EN SERIAL
 * =================================================================== */
static void printDownlink(const uint8_t* data, size_t len) {
    debug("[DOWNLINK] ");
    for (size_t i = 0; i < len; i++) debug("%02X ", data[i]);
    debug("-> \"");
    for (size_t i = 0; i < len; i++) {
        char c = (char)data[i];
        debug("%c", (c >= 32 && c <= 126) ? c : '.');
    }
    debug("\"\n");
}

/* ===================================================================
 *  ENVIAR PAYLOAD POR LORAWAN (modo manual)
 * =================================================================== */
static int sendAndReceiveManual(const uint8_t* data, size_t len) {
    if (len == 0) return RADIOLIB_ERR_NONE;
    debug(">> Enviando: ");
    for (size_t i = 0; i < len; i++) debug("%02X ", data[i]);
    downlinkLen = sizeof(downlinkData);
    int state = node.sendReceive(data, len, 1, downlinkData, &downlinkLen, false, NULL, NULL);
    if (state == RADIOLIB_ERR_NONE) {
        debug("-> OK (sin downlink)\n");
    } else if (state > 0 && downlinkLen > 0) {
        debug("-> OK + downlink (%d bytes)\n", (int)downlinkLen);
        printDownlink(downlinkData, downlinkLen);
    } else {
        debug("-> ERROR %d (%s)\n", state, stateDecode(state));
    }
    return state;
}

/* ===================================================================
 *  PROCESAR LINEA SERIAL (HEX → uplink, o comando ERASE)
 * =================================================================== */
static void processSerialLine(const char* line) {
    if (line[0] == '\0') return;

    if (strcmp(line, "ERASE") == 0 || strcmp(line, "erase") == 0) {
        hal_flash_erase(SESSION_PARTITION, 0, 4096);
        debug("[ERASE] Sesion borrada. Reiniciando...\n");
        delay(500);
        CySoftwareReset();
        return;
    }

    txLen = parseHexString(line, txBuffer, MAX_PAYLOAD);
    if (txLen == 0) {
        debug("?? Error: escribe hex valido. Ej: DE AD BE EF\n> ");
        Serial.flush();
        return;
    }
    if (!ensureJoined()) {
        debug("!! Sin sesion LoRaWAN\n> ");
        Serial.flush();
        return;
    }
    sendAndReceiveManual(txBuffer, txLen);
    lastUplinkMs = millis();
    debug("> ");
    Serial.flush();
}

/* ===================================================================
 *  SETUP
 * =================================================================== */
void setup() {
    Serial.begin(9600);
    delay(3000);
    debug("\n========================================\n");
    debug("  CubeCell LoRaWAN Demo (aislado)\n");
    debug("  AU915 | OTAA | Clase A\n");
    debug("========================================\n");

    board_init();   // inicializa tabla de particiones (para persistencia)

    int state = radio.begin();
    if (state != RADIOLIB_ERR_NONE) {
        debug("Radio init FAILED: %d\n", state);
        while (true) delay(1);
    }
    debug("Radio OK\n");

    state = node.beginOTAA(joinEui, devEui, nwkKey, appKey);
    if (state != RADIOLIB_ERR_NONE) {
        debug("Node init FAILED: %d\n", state);
        while (true) delay(1);
    }
    debug("Node OK\n");

    node.setSleepFunction(radioSleepDelay);
    node.scanGuard = 200;

    debug("Verificando sesion persistida...\n");
    loadSession();
    state = node.activateOTAA();
    if (state == RADIOLIB_LORAWAN_NEW_SESSION) {
        debug("+++ JOINED +++\n");
        saveSession();
    } else if (state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        debug("+++ SESION RESTAURADA (sin re-join) +++\n");
    } else {
        debug("Join FAILED: %d (%s)\n", state, stateDecode(state));
    }

    lastUplinkMs = millis();

    debug("----------------------------------------\n");
    debug("Heartbeat cada 30 s. Serial 9600 8N1.\n");
    debug("Modo manual: escribe HEX + Enter -> uplink.\n");
    debug("Comando ERASE: borra la sesion y reinicia.\n> ");
    Serial.flush();
}

/* ===================================================================
 *  LOOP
 * =================================================================== */
void loop() {
    /* 1) Modo manual: leer serial (HEX → uplink) */
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            if (serialPos > 0) {
                serialLine[serialPos] = '\0';
                processSerialLine(serialLine);
                serialPos = 0;
            }
        } else if (serialPos < SERIAL_BUF - 1) {
            serialLine[serialPos++] = c;
        }
    }

    /* 2) Heartbeat periodico: abre ventana RX para downlinks */
    if ((millis() - lastUplinkMs) >= HEARTBEAT_MS) {
        lastUplinkMs = millis();

        if (!node.isActivated()) {
            ensureJoined();
        }
        if (node.isActivated()) {
            downlinkLen = sizeof(downlinkData);
            int state = node.sendReceive(heartbeatPayload, heartbeatLen, 1,
                                         downlinkData, &downlinkLen, false, NULL, NULL);
            if (state > 0 && downlinkLen > 0) {
                debug("[HEARTBEAT] downlink recibido:\n");
                printDownlink(downlinkData, downlinkLen);
                debug("> ");
                Serial.flush();
            }
        }
    }

    delay(10);
}
