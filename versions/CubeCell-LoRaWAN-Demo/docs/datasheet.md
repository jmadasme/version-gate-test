# Datasheet — CubeCell-LoRaWAN-Demo

> Documentación de usuario y especificaciones técnicas del nodo LoRaWAN autónomo para demostraciones.

---

## 1. Resumen del producto

`CubeCell-LoRaWAN-Demo` es un nodo LoRaWAN **Clase A** basado en la placa **Heltec CubeCell HTCC-AB01**.
Opera en la región **AU915 sub-banda 2** con activación **OTAA**, y persiste la sesión en flash para
evitar re-enrolamientos. Está diseñado para **demostraciones educativas** del ciclo completo de un
dispositivo LoRaWAN (join, uplink, downlink, persistencia).

**Características clave:**

- Join OTAA y persistencia de sesión en flash (`PARAMETER_1`).
- Heartbeat de 1 byte (`0xBB`) cada 30 s (abre ventana RX para downlinks).
- Visualización de downlinks en el serial (`[DOWNLINK] XX XX -> "texto"`).
- Uplink manual escribiendo HEX por el puerto serie.
- Comando `ERASE` para borrar sesión y re-enrolar.
- Serial UART0 a 9600 baud 8N1 vía CP2102 (USB).

---

## 2. Especificaciones técnicas

### 2.1 Placa — Heltec CubeCell HTCC-AB01

| Parámetro | Valor |
|-----------|-------|
| MCU | ASR6502 (ASR Microelectronics) |
| Núcleo | ARM Cortex-M0+ @ 48 MHz |
| Flash | 128 KB |
| SRAM | 16 KB |
| Radio | Semtech SX1262 (LoRa/LoRaWAN Sub-GHz) |
| Frecuencias | 150–960 MHz (banda LoRa) |
| Modulación | LoRa / FSK / GFSK |
| Interfaces | UART (x2), I2C, SPI, ADC, GPIO |
| USB-UART | CP2102 |
| Antena | Conector U.FL / IPEX (antena externa) |
| Alimentación | 3.3 V (regulador interno desde 5 V USB) |
| Temperatura | -20 °C a +70 °C (típico) |

### 2.2 Radio — Semtech SX1262

| Parámetro | Valor |
|-----------|-------|
| Chip | SX1262 |
| Sensibilidad RX | hasta -148 dBm (SF12, BW125) |
| Potencia TX | hasta +22 dBm |
| Interfaz MCU | SPI + DIO1 (IRQ) + BUSY + RST |
| Pines (CubeCell) | NSS=35, DIO1=38, RST=47, BUSY=39 |

### 2.3 LoRaWAN — AU915

| Parámetro | Valor |
|-----------|-------|
| Región | AU915 (Australia, 915–928 MHz) |
| Sub-banda | 2 |
| Activación | OTAA |
| Clase | A |
| Versión LoRaWAN | 1.0.x (NwkKey = AppKey) |
| Payload máx. | 51 bytes (`MAX_PAYLOAD`) |
| Puerto uplink | 1 |
| Heartbeat | cada 30 s (`HEARTBEAT_MS`) |

### 2.4 Pinout interno

| Señal | GPIO ASR6502 | Función |
|-------|--------------|---------|
| NSS | 35 | SPI chip select |
| DIO1 | 38 | IRQ radio (TX/RX done) |
| RST | 47 | Reset radio |
| BUSY | 39 | Señal de ocupado |
| UART0 TX/RX | — | Consola serial (CP2102 → USB) |

---

## 3. Librerías requeridas e instalación

### 3.1 RadioLib 7.7.1

El firmware usa la librería **RadioLib** (implementación de LoRaWAN sobre SX1262). Debe ser la
versión **7.7.1**.

```bash
arduino-cli lib install "RadioLib@7.7.1"
```

> Si usas el IDE de Arduino: **Herramientas → Gestor de librerías** → buscar "RadioLib" → instalar
> la versión **7.7.1**.

### 3.2 Core de placa — Heltec CubeCell

```bash
arduino-cli config add board_manager.additional_urls \
  https://resource.heltec.cn/download/package_CubeCell_index.json
arduino-cli core update-index
arduino-cli core install CubeCell:CubeCell
```

> El core provee el SDK de ASR650x (`hal/soc/flash.h`, `board_init()`, `CySoftwareReset()`, etc.) y
> el soporte de la placa `CubeCell-Board`.

### 3.3 Otras dependencias

- **Ninguna adicional** — RadioLib y el SDK del core cubren todo.

---

## 4. Configuración del Network Server

### 4.1 The Things Network (TTN / The Things Stack)

1. Crea una aplicación.
2. **Registrar dispositivo → manual**.
3. Introduce:
   - **DevEUI** (de `credentials.h`)
   - **JoinEUI / AppEUI** (de `credentials.h`)
   - **AppKey** (de `credentials.h`)
4. **Frequency plan:** `Australia 915-928 MHz (AU915-928)` — sub-banda 2.
5. Guarda y verifica que el dispositivo pueda unirse.
6. Pega el decoder en *Payload formatters* (ver `README.md` §7.3).

### 4.2 ChirpStack

1. Crea un **device profile** (región AU915, sub-banda 2, Clase A, OTAA).
2. Crea una **aplicación** y añade el dispositivo (DevEUI + JoinEUI + AppKey).
3. Configura el **gateway** y el *service profile*.
4. Pega el decoder en el *codec* del device profile.

### 4.3 Helium

1. En Helium Console crea un dispositivo con el DevEUI.
2. Configura la integración (ChirpStack/Helium) con JoinEUI y AppKey.
3. Verifica la sub-banda AU915.

### 4.4 Milesight (Network Server embebido en el gateway)

1. Web UI del gateway (ej. UG56) → crear red LoRaWAN en **AU915 sub-banda 2**.
2. Añadir dispositivo OTAA con DevEUI + JoinEUI + AppKey.
3. Habilita el **NS embebido** y comprueba el join.

---

## 5. Guía de solución de problemas

### 5.1 `Radio init FAILED`

- La radio SX1262 no responde por SPI.
- **Causas:** mala soldadura, antena no conectada no afecta al init (pero no transmitas sin ella),
  core de CubeCell no instalado, pines SPI incorrectos.
- **Solución:** reinstalar el core `CubeCell:CubeCell`, verificar el cableado/alimentación, y
  confirmar que la placa seleccionada es `CubeCell-Board`.

### 5.2 `NO_JOIN_ACCEPT` (join falla)

- El Network Server no acepta el join.
- **Causas:** credenciales incorrectas (DevEUI/JoinEUI/AppKey), región/sub-banda incorrecta en el
  gateway o NS, gateway fuera de alcance, puerto/antena.
- **Solución:**
  1. Verifica que `credentials.h` coincida **exactamente** con lo registrado en el NS.
  2. Confirma que el gateway y el NS estén en **AU915 sub-banda 2**.
  3. Asegúrate de que el gateway escucha la sub-banda 2.
  4. Revisa la antena y la distancia.

### 5.3 `JOIN_NONCE_INVALID` (-1116)

- Ocurre cuando el **Network Server fue reiniciado** y el `JoinNonce` se reseteó, mientras el
  dispositivo mantiene un `DevNonce` alto con una sesión persistida.
- **Solución:** enviar el comando `ERASE` por el serial. Esto borra la sesión persistida y re-enrola
  limpiamente.

### 5.4 No hay uplink

- El nodo no transmite o el NS no lo ve.
- **Causas:** sesión no activa (`NOT_JOINED`), sub-banda incorrecta, duty cycle agotado, potencia
  insuficiente, antena desconectada.
- **Solución:**
  1. Verifica en el serial que el join/restauración fue exitoso.
  2. Revisa la sub-banda 2 en gateway y NS.
  3. Conecta la antena y acerca el nodo al gateway.
  4. Espera el *duty cycle* (AU915 es estricto).

### 5.5 El downlink no llega

- El heartbeat se envía pero no hay downlink en el serial.
- **Causas:** el NS no envió downlink, la ventana RX1/RX2 no coincide (retardo), el downlink se
  envía fuera de la ventana Clase A.
- **Solución:**
  1. Confirma que enviaste un downlink **después** de un uplink (Clase A solo abre RX tras uplink).
  2. Verifica el *payload formatter* de downlink (encoder) en el NS.
  3. Asegúrate de que el downlink usa el **puerto 1**.
  4. Revisa los parámetros de ventana RX1/RX2 (datarate/offset) en el NS.

### 5.6 `NOT_JOINED`

- Se intentó enviar sin sesión activa.
- **Solución:** el firmware ya reintenta (`ensureJoined`). Si persiste, revisa las credenciales y
  envía `ERASE` para re-enrolar.

---

## 6. Nota de credenciales

- **`credentials.h`** — contiene las credenciales **reales** (JoinEUI, DevEUI, AppKey, NwkKey).
  Está **ignorado por git**. **Nunca lo publiques.**
- **`credentials.example.h`** — plantilla segura con todos los valores a cero. Para compartir o
  comenzar un nuevo nodo, copia la plantilla y completa tus valores:

```bash
cp credentials.example.h credentials.h
```

Luego edita:

```c
uint64_t joinEui = 0x0000000000000000;   // tu JoinEUI/AppEUI
uint64_t devEui  = 0x0000000000000000;   // tu DevEUI
uint8_t appKey[] = { /* 16 bytes */ };
uint8_t nwkKey[] = { /* 16 bytes, = appKey en LoRaWAN 1.0.x */ };
```

> Los valores son `uint64_t` en formato **LSB-first** según RadioLib. Verifica el orden de bytes al
> copiar de la consola del NS (TTN muestra DevEUI/JoinEUI en MSB-first; RadioLib usa el orden nativo
> de memoria, por lo que a veces hay que invertir los bytes).

---

## 7. Tabla de compatibilidad con otras placas LoRaWAN

| Placa | Radio | ¿Compatible? | Notas |
|-------|-------|--------------|-------|
| Heltec CubeCell HTCC-AB01 | SX1262 | ✅ **Placa objetivo** | — |
| Heltec CubeCell HTCC-AB02 | SX1262 | ✅ | Mismo ASR6502 + SX1262; mismo pinout |
| Heltec CubeCell Board (lite) | SX1262 | ✅ | Puede requerir ajuste de pines |
| Heltec CubeCell GPS-6502 | SX1262 | ✅ | Añade GPS; el firmware LoRaWAN es compatible |
| LilyGO T-Beam (TTGO LoRa32) | SX1276/SX1278 | ⚠️ Parcial | Distinto MCU (ESP32) y radio; requiere reescribir pines y persistencia |
| Heltec WiFi LoRa 32 (V2/V3) | SX1262 (V2) / SX1276 | ⚠️ Parcial | ESP32; pines distintos, sin `hal_flash` de ASR |
| RAK4631 (nRF52840) | SX1262 | ⚠️ Parcial | Radio compatible, pero MCU nRF y SDK distintos |
| Adafruit Feather M0 LoRa | RFM95 (SX1276) | ❌ | Radio distinta (SX1276) |

> **Regla general:** el firmware asume **ASR650x + SX1262 + SDK Heltec** (`hal/soc/flash.h`,
> `board_init()`, `CySoftwareReset()`). Para otras MCU/radios hay que adaptar la capa de hardware y
> la persistencia (ver `docs/developer.md`).

---

## 8. Aplicación de escritorio (GUI) — `cubecell_gui.py`

El nodo también se puede operar desde el PC con una **GUI de escritorio** (Python + PyQt6) en lugar
del monitor serial. La guía completa de usuario está en **`docs/gui_cubecell.md`**.

### 8.1 Especificaciones de la GUI

| Parámetro | Valor |
|-----------|-------|
| Archivo | `cubecell_gui.py` (~700 líneas, un solo archivo) |
| Dependencias | `pyserial >= 3.5`, `PyQt6 >= 6.4` |
| Baudrate | 9600 8N1 (igual al firmware) |
| Máx. payload uplink | 51 bytes (`MAX_PAYLOAD`) |
| Detección de puerto | Auto-sonda: envía `x` y espera `?? Error: escribe hex valido` |
| Tema | Oscuro premium estilo RAF (mismo que `espnow_gui`/`valvulas_gui`) |

### 8.2 Instalación y ejecución

```bash
pip install -r requirements.txt
python3 cubecell_gui.py     # dentro de CubeCell-LoRaWAN-Demo
```

En Linux, el usuario debe pertenecer al grupo `dialout` (`sudo usermod -aG dialout $USER`) y
re-loguear.

### 8.3 Funciones clave

- Terminal serial coloreado en vivo.
- Uplink en modo HEX o ASCII (puerto 1 LoRaWAN).
- Lista de downlinks `[DOWNLINK] XX XX -> "texto"` con timestamp.
- Indicadores de sesión (JOINED/RESTAURADA/SIN JOIN), radio, heartbeats, uplinks, downlinks, RX/TX.
- Comando **ERASE** con confirmación.
- Auto-detección del puerto del CubeCell (no siempre es `/dev/ttyUSB0`; en esta instalación es
  `/dev/ttyUSB1`).

> **Detalle importante:** el firmware solo imprime cuando ocurre algo (banner al arrancar, eco de
> uplink, downlink). Con el nodo en reposo el terminal parecerá "quieto" — es normal; no hay flujo
> continuo de datos.
