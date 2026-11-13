# Developer Guide — CubeCell-LoRaWAN-Demo

> Explicación del código fuente, persistencia de sesión y guía de modificación del nodo LoRaWAN.

---

## 1. Arquitectura general

El firmware es un **programa secuencial de un solo archivo** (`CubeCell-LoRaWAN-Demo.ino`), con el
clásico modelo `setup()` / `loop()` de Arduino. Se organiza en estas capas:

```
+--------------------------------------------------------------+
|  setup()                                                     |
|   - Inicializa serial (9600)                                 |
|   - board_init() (tabla de particiones flash)                |
|   - radio.begin() + node.beginOTAA(...)                      |
|   - loadSession() + activateOTAA() (join o restauración)     |
|   - Configura sleep workaround + scanGuard                   |
+--------------------------------------------------------------+
|  loop()                                                      |
|   1. Procesar serial (HEX → uplink, o ERASE)                 |
|   2. Heartbeat cada 30 s (sendReceive → abre RX para downlink)|
+--------------------------------------------------------------+
```

**Bibliotecas y dependencias:**

| Dependencia | Uso |
|-------------|-----|
| `RadioLib.h` | Abstracción SX1262 + pila LoRaWAN (`LoRaWANNode`) |
| `credentials.h` | Credenciales OTAA (JoinEUI, DevEUI, AppKey, NwkKey) |
| `hal/soc/flash.h` | API de flash del SDK ASR650x (persistencia) |
| `board_init()` | Inicializa la tabla de particiones del SDK |

---

## 2. Constantes y objetos globales

```c
Module mod(35, 38, 47, 39);          // NSS, DIO1, RST, BUSY (SX1262)
SX1262 radio(&mod);                   // Objeto radio
const LoRaWANBand_t Region = AU915;   // Región
const uint8_t subBand = 2;            // Sub-banda
LoRaWANNode node(&radio, &Region, subBand);  // Nodo LoRaWAN

#define MAX_PAYLOAD     51            // Payload máx. de uplink
#define HEARTBEAT_MS    30000UL       // Heartbeat cada 30 s
#define SERIAL_BUF      256           // Buffer de línea serial
```

| Variable global | Tipo | Propósito |
|-----------------|------|-----------|
| `downlinkData[]` | `uint8_t[MAX_PAYLOAD]` | Buffer de recepción de downlink |
| `downlinkLen` | `size_t` | Longitud del downlink recibido |
| `lastUplinkMs` | `uint32_t` | Timestamp del último uplink (para heartbeat) |
| `txBuffer[]` / `txLen` | `uint8_t[]/size_t` | Payload a enviar en modo manual |
| `serialLine[]` / `serialPos` | `char[]/size_t` | Buffer de línea serial acumulada |
| `heartbeatPayload` | `const uint8_t[]` | Payload fijo `{0xBB}` |
| `persistSession[]` | `uint8_t[RADIOLIB_LORAWAN_SESSION_BUF_SIZE]` | Buffer de sesión persistida |
| `persistNonces[]` | `uint8_t[RADIOLIB_LORAWAN_NONCES_BUF_SIZE]` | Buffer de nonces persistidos |

---

## 3. `setup()` — Inicialización

```c
void setup() {
    Serial.begin(9600);            // UART0 9600 8N1
    delay(3000);                   // Espera a que se abra el monitor
    // ... banner ...
    board_init();                  // Inicializa tabla de particiones (flash)

    int state = radio.begin();     // Init SX1262
    // si falla → bucle infinito

    state = node.beginOTAA(joinEui, devEui, nwkKey, appKey);
    // si falla → bucle infinito

    node.setSleepFunction(radioSleepDelay);  // workaround ASR6502
    node.scanGuard = 200;                   // tiempo de guarda en RX

    loadSession();                 // Lee buffers de flash y los inyecta
    state = node.activateOTAA();   // Join o restauración

    if (state == RADIOLIB_LORAWAN_NEW_SESSION) {
        // join completo → guardar sesión
        saveSession();
    } else if (state == RADIOLIB_LORAWAN_SESSION_RESTORED) {
        // sesión restaurada, no re-join
    } else {
        // error de join
    }

    lastUplinkMs = millis();
}
```

**Puntos importantes:**

- `board_init()` **debe** llamarse antes de usar `hal_flash_*` (prepara la tabla de particiones).
- El orden de `beginOTAA(...)` con los argumentos es: `(joinEui, devEui, nwkKey, appKey)`.
- `node.setSleepFunction(radioSleepDelay)` instala un *sleep* basado en `millis()` porque el timer
  del ASR6502 tiene un bug conocido; sin esto, RadioLib podría dormirse incorrectamente.

---

## 4. `loop()` — Bucle principal

```c
void loop() {
    // 1) Modo manual: leer serial
    while (Serial.available() > 0) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {        // fin de línea
            if (serialPos > 0) {
                serialLine[serialPos] = '\0';
                processSerialLine(serialLine);
                serialPos = 0;
            }
        } else if (serialPos < SERIAL_BUF - 1) {
            serialLine[serialPos++] = c;     // acumular
        }
    }

    // 2) Heartbeat periódico
    if ((millis() - lastUplinkMs) >= HEARTBEAT_MS) {
        lastUplinkMs = millis();
        if (!node.isActivated()) ensureJoined();
        if (node.isActivated()) {
            downlinkLen = sizeof(downlinkData);
            int state = node.sendReceive(heartbeatPayload, heartbeatLen, 1,
                                         downlinkData, &downlinkLen, false, NULL, NULL);
            if (state > 0 && downlinkLen > 0) {
                printDownlink(downlinkData, downlinkLen);
            }
        }
    }
    delay(10);
}
```

---

## 5. Persistencia de sesión (detalle)

### 5.1 Objetivo

Evitar el re-enrolamiento OTAA en cada arranque. El join OTAA consume `DevNonce` (y el NS consume
`JoinNonce`); re-enrolar sin necesidad agota contadores y puede producir conflictos. La sesión
derivada (`NwkSKey`, `AppSKey`, contadores de frame) se guarda en flash.

### 5.2 Buffers de RadioLib

- `node.getBufferSession()` → puntero al buffer que RadioLib usa para serializar la sesión
  (claves de sesión, `DevAddr`, contadores de frame, etc.).
- `node.getBufferNonces()` → puntero al buffer con los nonces (contadores de join).
- `node.setBufferSession(ptr)` / `node.setBufferNonces(ptr)` → inyectan los buffers restaurados.

### 5.3 Funciones de persistencia

```c
#define SESSION_PARTITION HAL_PARTITION_PARAMETER_1

static void saveSession(void) {
    uint8_t* s = node.getBufferSession();
    uint8_t* n = node.getBufferNonces();
    uint32_t off = 0;
    hal_flash_erase(SESSION_PARTITION, 0, 4096);              // borra la partición
    off = 0;
    hal_flash_write(SESSION_PARTITION, &off, s, RADIOLIB_LORAWAN_SESSION_BUF_SIZE);
    hal_flash_write(SESSION_PARTITION, &off, n, RADIOLIB_LORAWAN_NONCES_BUF_SIZE);
}

static void loadSession(void) {
    uint32_t off = 0;
    hal_flash_read(SESSION_PARTITION, &off, persistSession, RADIOLIB_LORAWAN_SESSION_BUF_SIZE);
    hal_flash_read(SESSION_PARTITION, &off, persistNonces, RADIOLIB_LORAWAN_NONCES_BUF_SIZE);
    // Orden importante: primero nonces, luego sesión
    node.setBufferNonces(persistNonces);
    node.setBufferSession(persistSession);
}
```

**Claves:**

- Se usa la partición `HAL_PARTITION_PARAMETER_1` (zona de "parámetros" reservada por el SDK).
- `hal_flash_write/read` avanzan el offset automáticamente vía el puntero `off`.
- En `loadSession()`, el orden de `setBufferNonces` **antes** de `setBufferSession` es importante
  (así lo indica el comentario del código y la API de RadioLib).

### 5.4 Flujo de activación con persistencia

```
setup()
  └─ loadSession()               (lee flash → inyecta buffers)
        └─ node.activateOTAA()
              ├─ ¿buffers válidos? → SESSION_RESTORED  (no re-join)
              └─ sin sesión → join OTAA real → NEW_SESSION → saveSession()
```

---

## 6. Funciones clave (API interna)

### 6.1 `radioSleepDelay(RadioLibTime_t ms)`

Workaround del bug del timer del ASR6502. Implementa un delay basado en `millis()`:

```c
static void radioSleepDelay(RadioLibTime_t ms) {
    if (ms == 0) return;
    uint32_t start = millis();
    while ((millis() - start) < ms) { /* NOP */ }
}
```

Se instala con `node.setSleepFunction(radioSleepDelay)`.

### 6.2 `stateDecode(int16_t s)`

Convierte un código de estado de RadioLib a una cadena legible. Cubre los códigos más relevantes
(`RADIOLIB_ERR_NONE`, `RADIOLIB_ERR_CHIP_NOT_FOUND`, `RADIOLIB_ERR_RX_TIMEOUT`,
`RADIOLIB_ERR_NETWORK_NOT_JOINED`, `RADIOLIB_ERR_NO_JOIN_ACCEPT`,
`RADIOLIB_ERR_JOIN_NONCE_INVALID`, `RADIOLIB_LORAWAN_NEW_SESSION`,
`RADIOLIB_LORAWAN_SESSION_RESTORED`).

### 6.3 `ensureJoined()`

```c
static bool ensureJoined(void) {
    if (node.isActivated()) return true;
    // reintenta activateOTAA y, si hay sesión nueva, la guarda
}
```

Devuelve `true` si hay sesión activa. Se usa antes de un uplink manual y antes del heartbeat, para
reintentar el join si la sesión se perdió.

### 6.4 `parseHexString(const char* input, uint8_t* output, size_t maxOut)`

Convierte una cadena HEX (`"DE AD BE EF"` o `"DEADBEEF"`) a bytes. Ignora cualquier carácter no
hexadecimal (espacios, `:`, etc.). Devuelve el número de bytes, o `0` si la longitud es impar o no
hay dígitos.

### 6.5 `printDownlink(const uint8_t* data, size_t len)`

Imprime un downlink en el serial:

```
[DOWNLINK] 48 4F 4C 41 -> "HOLA"
```

Muestra cada byte en HEX y su interpretación ASCII (no imprimibles → `.`).

### 6.6 `sendAndReceiveManual(const uint8_t* data, size_t len)`

Envía un uplink (puerto 1) y espera el downlink en la ventana RX:

```c
int state = node.sendReceive(data, len, 1, downlinkData, &downlinkLen, false, NULL, NULL);
```

- `state == RADIOLIB_ERR_NONE` → enviado, sin downlink.
- `state > 0 && downlinkLen > 0` → enviado y recibió downlink (lo imprime).
- otro → error.

### 6.7 `processSerialLine(const char* line)`

Procesa una línea del serial:

- Si es `ERASE`/`erase` → borra la sesión flash y reinicia (`CySoftwareReset()`).
- Si no → parsea HEX y, si hay sesión, llama a `sendAndReceiveManual(...)`.

---

## 7. Diagrama de flujo de la lógica principal

```
                        +-------------------+
                        |      setup()      |
                        +-------------------+
                                   |
                    +--------------+--------------+
                    | Inicializar serial 9600      |
                    | board_init() (flash)         |
                    | radio.begin()                |
                    | node.beginOTAA(...)          |
                    | setSleepFunction(...)        |
                    +--------------+--------------+
                                   |
                          loadSession()  (flash → buffers)
                                   |
                          node.activateOTAA()
                                   |
              +--------------------+--------------------+
              |                    |                    |
        NEW_SESSION        SESSION_RESTORED        ERROR
              |                    |                    |
        saveSession()        (no re-join)        print error
              |                    |                    |
              +--------------------+--------------------+
                                   |
                        +----------v----------+
                        |       loop()        |
                        +----------+----------+
                                   |
              +--------------------+--------------------+
              |                                         |
     [Serial disponible]                      [millis()-lastUplink >= 30s]
              |                                         |
    acumular hasta '\n'                        lastUplink = millis()
              |                                         |
    processSerialLine(line)                     ¿node.isActivated()?
              |                                         |
      +-------+-------+                          no → ensureJoined()
      |               |                               |
    "ERASE"       HEX válido                     sendReceive(0xBB)  (heartbeat)
      |               |                               |
   borrar flash   sendAndReceiveManual()         ¿downlink recibido?
   reiniciar            |                               |
                      (print result)              sí → printDownlink()
```

---

## 8. Guía de modificación y extensión

### 8.1 Cambiar la región

En `CubeCell-LoRaWAN-Demo.ino`, modifica `Region`:

```c
const LoRaWANBand_t Region = EU868;   // en lugar de AU915
```

Valores disponibles en RadioLib: `EU868`, `US915`, `AU915`, `AS923`, `IN865`, `KR920`, `CN780`,
`EU433`, etc. Ajusta también `subBand` si aplica (US915/AU915 usan sub-bandas 0–7; otras regiones
ignoran la sub-banda).

### 8.2 Cambiar la sub-banda

```c
const uint8_t subBand = 2;   // cámbialo a la sub-banda de tu gateway (0..7 para AU915/US915)
```

### 8.3 Cambiar credenciales

Edita `credentials.h` (o crea uno desde la plantilla):

```bash
cp credentials.example.h credentials.h
```

Actualiza `joinEui`, `devEui`, `appKey`, `nwkKey`. Para LoRaWAN 1.0.x, `nwkKey` debe ser igual a
`appKey`.

### 8.4 Cambiar la frecuencia del heartbeat

```c
#define HEARTBEAT_MS 30000UL   // cámbialo a, p.ej., 60000UL (60 s)
```

### 8.5 Cambiar el payload del heartbeat

```c
const uint8_t heartbeatPayload[] = { 0xBB };   // cambia los bytes
const size_t  heartbeatLen = 1;                // y la longitud
```

### 8.6 Agregar un sensor

1. Inicializa el sensor en `setup()` (I2C/ADC/GPIO).
2. Lee el sensor en `loop()` y arma un payload multi-byte (respetando `MAX_PAYLOAD`).
3. Reemplaza `heartbeatPayload` por tu buffer de sensor (o crea una nueva variable).
4. Actualiza el decoder en el NS (ver `README.md` §7.3).

Ejemplo mínimo:

```c
// En loop(), dentro del bloque de heartbeat:
uint8_t sensorPayload[4];
float temp = readTemperature();              // tu sensor
memcpy(sensorPayload, &temp, sizeof(float)); // endianidad: define el orden
downlinkLen = sizeof(downlinkData);
int state = node.sendReceive(sensorPayload, sizeof(sensorPayload), 1,
                             downlinkData, &downlinkLen, false, NULL, NULL);
```

### 8.7 Cambiar el payload manual (máx. 51 bytes)

`MAX_PAYLOAD` limita el tamaño del uplink manual. Para payloads mayores, ajústalo (respetando el
límite de la región AU915, típicamente ~242 bytes en el peor SF, pero verifica el *datarate* y el
*duty cycle*).

### 8.8 Persistencia en otra partición

`SESSION_PARTITION` está definido como `HAL_PARTITION_PARAMETER_1`. Si necesitas otra partición,
consulta la tabla de particiones del SDK ASR650x y cambia la macro. Asegúrate de que el tamaño de
borrado (4096) coincida con el tamaño de sector de tu partición.

### 8.9 Reinicio limpio del join

Si cambias las credenciales o reinicias el NS, envía `ERASE` por serial (o llama a
`hal_flash_erase(SESSION_PARTITION, 0, 4096)` programáticamente) para forzar un re-join limpio.

---

## 9. Códigos de estado relevantes de RadioLib

| Código (constante) | Valor típico | Significado |
|--------------------|--------------|-------------|
| `RADIOLIB_ERR_NONE` | 0 | Éxito |
| `RADIOLIB_ERR_CHIP_NOT_FOUND` | negativo | SX1262 no responde |
| `RADIOLIB_ERR_RX_TIMEOUT` | negativo | Ventana RX expiró sin downlink |
| `RADIOLIB_ERR_NETWORK_NOT_JOINED` | negativo | Sin sesión activa |
| `RADIOLIB_ERR_NO_JOIN_ACCEPT` | negativo | Join rechazado |
| `RADIOLIB_ERR_JOIN_NONCE_INVALID` | negativo (-1116) | JoinNonce del NS reiniciado |
| `RADIOLIB_LORAWAN_NEW_SESSION` | positivo | Join OTAA completado |
| `RADIOLIB_LORAWAN_SESSION_RESTORED` | positivo | Sesión restaurada desde buffers |

---

## 10. Notas de implementación y advertencias

- **Bug de timer ASR6502:** el SDK del ASR650x tiene un timer poco fiable para sleeps cortos; por
  eso se usa `radioSleepDelay()` basado en `millis()`.
- **`node.scanGuard = 200`:** añade 200 ms de guarda antes/después de las ventanas RX para compensar
  la latencia del timer.
- **No modificar el orden** `setBufferNonces` → `setBufferSession` en `loadSession()`.
- **`board_init()`** debe ejecutarse antes de cualquier `hal_flash_*`.
- **Nunca** subir `credentials.h` a un repositorio público.

---

## 11. Aplicación de escritorio — `cubecell_gui.py`

### 11.1 Arquitectura general

La GUI es una **aplicación PyQt6 de un solo archivo** que replica la consola del firmware en una
interfaz oscura estilo RAF. Misma paleta y estructura que `espnow_gui.py` / `valvulas_gui.py`.

```
┌────────────────────────────────────────────────────────────────┐
│ SerialReader(QThread)     detect_ports() / probe_cubecell()    │
│   - lee byte a byte          - lista /dev/ttyUSB*               │
│   - emite line_received      - sondea responda "escribe hex"    │
│   - prompt "> " exacto                                          │
└───────────────▲────────────────────────────────────────────────┘
                │ pyqtSignal(str) → MainWindow.on_line()
┌───────────────┴────────────────────────────────────────────────┐
│ MainWindow                                                    │
│   - refresh_ports()  → auto-selección del CubeCell            │
│   - connect_serial() / disconnect_serial() / _write()         │
│   - send_uplink()    → HEX o ASCII, con validaciones          │
│   - do_erase()       → confirma y envía ERASE                 │
│   - on_line() → _classify() → append_log() + estadísticas     │
│   - Tarjetas: Indicadores · Downlinks · Terminal · Uplink      │
└────────────────────────────────────────────────────────────────┘
```

**Dependencias:** `pyserial` (puerto serie + `list_ports`) y `PyQt6` (widgets, `QThread`).

### 11.2 Constantes y expresiones del protocolo

```python
BAUD = 9600
MAX_PAYLOAD = 51                      # igual al firmware

RE_DOWNLINK = re.compile(r"\[DOWNLINK\]\s+((?:[0-9A-F]{2}\s+)+)->\s*\"([^\"]*)\"")
RE_SENDING  = re.compile(r">>\s*Enviando:\s+((?:[0-9A-F]{2}\s+)+)")
RE_OK_DL    = re.compile(r"-> OK \+ downlink \((\d+) bytes\)")
RE_ERROR    = re.compile(r"-> ERROR (-?\d+) \(([^)]+)\)")
```

### 11.3 `SerialReader` — hilo lector

- QThread que lee el puerto **byte a byte** (`read(1)` con timeout 0.2 s) para no bloquear la UI.
- Detecta fin de línea por `\n`/`\r` y emite `line_received`.
- **Prompt sin newline**: cuando el buffer es **exactamente** `b"> "` se emite `"> "` y se limpia.
  Esto evita el falso positivo del `-> ` dentro de `DE AD BE EF -> OK` (que sí contiene `> ` al
  final) y separa el prompt del siguiente mensaje.

### 11.4 `detect_ports()` y `probe_cubecell()`

- `detect_ports()`: lista puertos `ttyUSB*`/`ttyACM*`/`usb*` con `list_ports.comports()`.
- `probe_cubecell(device)`: abre el puerto a 9600, envía `x\n` (sonda **inofensiva**: no genera
  uplink ni borra nada) y comprueba que el firmware responda `?? Error: escribe hex valido`. Con
  ello identifica de forma fiable cuál de los CP210x es el CubeCell (en esta instalación:
  `/dev/ttyUSB1`, mientras `/dev/ttyUSB0` es el bridge ESP-NOW).

### 11.5 `MainWindow` — métodos principales

| Método | Función |
|--------|---------|
| `refresh_ports()` | Re-detecta y, si hay ≤ 4 puertos, sondea con `probe_cubecell()` y auto-selecciona el CubeCell. |
| `toggle_connection()` / `connect_serial()` / `disconnect_serial()` | Abre/cierra el puerto a 9600 8N1; arranca/para el `SerialReader`. |
| `set_status(connected, port)` | Actualiza el botón de conexión y la barra de estado. |
| `_write(raw)` | Escribe bytes al puerto y acumula `RX`/`TX`. |
| `send_uplink()` | Valida y envía: modo HEX (pares 0-9A-F, max 51 B) o ASCII (Latin-1). Los errores van al log en rojo (sin diálogos modales). |
| `do_erase()` | Con `QMessageBox.question` de confirmación, envía `ERASE`. |
| `on_line(line)` | Suma bytes RX y delega en `_classify()`. |
| `_classify(line)` | Colorea la línea, actualiza contadores (uplinks/downlinks/heartbeats), lista downlinks, actualiza sesión/radio y la barra de estado. |
| `_update_stats()` / `_update_time()` | Refresca los QLabel de estadísticas (QTimer de 1 s). |
| `append_log(text, color, bold)` | Escapa HTML y hace `appendHtml` al terminal (QPlainTextEdit en modo solo-lectura). |

### 11.6 Mapeo protocolo serial → comportamiento de la GUI

| Línea del firmware | Comportamiento de la GUI |
|--------------------|--------------------------|
| `>> Enviando: XX XX -> ...` | Negrita teal; `UL++` (RE_SENDING). |
| `-> OK (sin downlink)` / `-> OK + downlink (n)` | Verde. |
| `-> ERROR n (txt)` | Rojo (RE_ERROR). |
| `[DOWNLINK] XX XX -> "texto"` | Verde; `DL++`; inserta en la lista: `HH:MM:SS HEX → "texto"`. |
| `[HEARTBEAT] downlink recibido:` | Azul; `HB++`. |
| `Radio OK` | Indicador radio → `OK ✓`. |
| `Radio init FAILED: n` | Indicador radio → `FALLO`. |
| `+++ JOINED +++` | Indicador sesión → `JOINED ✓`. |
| `+++ SESION RESTAURADA +++` | Indicador sesión → `RESTAURADA`. |
| `Join FAILED` / `NO_JOIN_ACCEPT` | Indicador sesión → `SIN JOIN`. |
| `> ` (prompt) | Gris; no cuenta en estadísticas. |

### 11.7 Extender la GUI

- **Agregar un nuevo comando al nodo**: el firmware de CubeCell no tiene más comandos; si el
  firmware evoluciona, añade un botón y en su handler haz `self._write(b"COMANDO\n")`, luego
  clasifica la respuesta en `_classify()`.
- **Cambiar región/credenciales**: se hace en el firmware; la GUI solo refleja el serial.
- **Añadir gráficas de RSSI/SNR**: RadioLib no expone esos campos en esta demo; tendrías que añadir
  el campo al payload del firmware y parsearlo en `_classify()`.
- **Añadir telemetría programada**: la GUI es pasiva (terminal); para automatización, consulta
  `docs/gui_cubecell.md` y añade una pestaña con QTimer que envíe uplinks periódicos.
