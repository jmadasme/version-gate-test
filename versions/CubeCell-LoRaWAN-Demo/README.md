# CubeCell-LoRaWAN-Demo

> **Nodo LoRaWAN autónomo y aislado para demostraciones**
> Heltec CubeCell HTCC-AB01 · ASR6502 + SX1262 · AU915 sub-banda 2 · OTAA Clase A · RadioLib 7.7.1

---

## 1. Descripción del proyecto

`CubeCell-LoRaWAN-Demo` es un firmware de **demostración autónoma de LoRaWAN** para la placa
Heltec CubeCell HTCC-AB01. El nodo opera de forma **aislada** (no necesita un puente a otras redes
como ESP-NOW o WiFi): se comunica directamente con un *gateway* LoRaWAN y un *Network Server*.

El objetivo del proyecto es demostrar, de forma reproducible, el ciclo de vida completo de un
dispositivo LoRaWAN Clase A:

1. **Join OTAA** (Over-The-Air Activation) contra el Network Server.
2. **Persistencia de sesión** en flash para **no re-enrolar** en cada reinicio.
3. **Heartbeat periódico** (cada 30 s) que abre la ventana de recepción RX.
4. **Recepción de downlinks** y su visualización en el monitor serial.
5. **Uplink manual** escribiendo bytes HEX por el puerto serie.
6. **Borrado de sesión** (`ERASE`) para resolver conflictos de `JoinNonce`/`DevNonce`.

Además del firmware, el repositorio incluye **`cubecell_gui.py`**, un panel de control de escritorio
(Python + PyQt6) que sustituye al monitor serial: terminal en vivo, envío de uplinks HEX/ASCII,
recepción de downlinks, indicadores de sesión/radio y comando ERASE desde una GUI oscura estilo RAF
(ver la sección 14 *Aplicación de escritorio* más abajo).

> **Importante:** este proyecto es una demo de propósito educativo/demostrativo. No incluye
> sensores físicos; el payload por defecto es fijo (`0xBB`), y los datos adicionales se envían
> manualmente por el puerto serie.

---

## 2. Placa objetivo y especificaciones

| Parámetro | Valor |
|-----------|-------|
| **Placa** | Heltec CubeCell **HTCC-AB01** |
| **MCU** | ASR6502 (ASR Microelectronics) — núcleo ARM Cortex-M0+ @ 48 MHz |
| **Radio LoRa** | Semtech **SX1262** (LoRa/LoRaWAN, banda Sub-GHz) |
| **Flash** | 128 KB (programa) — ver nota más abajo |
| **SRAM** | 16 KB |
| **Conectividad** | LoRaWAN Clase A/B/C (aquí se usa **Clase A**) |
| **Alimentación** | 3.3 V (regulador integrado; entrada USB 5 V vía CP2102) |
| **Interfaz USB** | CP2102 (USB-UART) |
| **Antena** | Conector U.FL / IPEX (antena externa obligatoria) |
| **Región LoRaWAN** | **AU915** (Australia) sub-banda **2** |
| **Método de activación** | **OTAA** (Over-The-Air Activation) |
| **Clase** | **A** (ventanas RX1/RX2 tras cada uplink) |
| **Librería radio** | RadioLib **7.7.1** |
| **Serial** | UART0 a **9600 baud 8N1** |

> **Nota sobre Flash/RAM:** el ASR6502 integra 128 KB de flash y 16 KB de SRAM. Parte del flash se
> usa para almacenar la **sesión LoRaWAN persistida** (partición `PARAMETER_1`), por lo que el nodo
> puede reiniciarse sin perder la sesión de red.

---

## 3. Principio de funcionamiento

### 3.1 Flujo general

```
+--------------+     OTAA Join      +------------------+
|  CubeCell    |  <==============>  |  Gateway LoRaWAN |
|  HTCC-AB01   |  uplink/downlink   |  (ej. UG56/UG63) |
+--------------+                    +--------+---------+
       |  UART0 9600                         |
       |  (CP2102 USB)                       v
+--------------+                    +------------------+
|  PC / Serial |                    |  Network Server  |
|  Monitor     |                    | (TTN/ChirpStack) |
+--------------+                    +------------------+
```

### 3.2 Activación OTAA (join)

El dispositivo se activa por **OTAA**. En el arranque:

1. Se inicializa la radio (`radio.begin()`).
2. Se configura el nodo LoRaWAN con las credenciales OTAA (`node.beginOTAA(...)`).
3. Se intenta **restaurar** una sesión persistida (ver 3.3).
4. Si no hay sesión válida, se lanza `activateOTAA()`, que ejecuta el *join request / join accept*
   contra el Network Server y deriva las claves de sesión `NwkSKey` y `AppSKey`.

Las credenciales OTAA se encuentran en `credentials.h`:

| Credencial | Campo en el código | Descripción |
|-----------|-------------------|-------------|
| **JoinEUI / AppEUI** | `joinEui` | Identificador de red (8 bytes) |
| **DevEUI** | `devEui` | Identificador único del dispositivo (8 bytes) |
| **AppKey** | `appKey` | Clave raíz de aplicación (16 bytes) |
| **NwkKey** | `nwkKey` | Clave raíz de red; en LoRaWAN 1.0.x es igual a `AppKey` |

> ⚠️ **Nunca publiques valores reales.** Este proyecto usa `credentials.h` (ignorado por git) y
> `credentials.example.h` como plantilla segura. Ver [sección 8](#8-configuración-lorawan).

### 3.3 Persistencia de sesión (evita el re-join)

Para **no re-enrolar en cada arranque**, el firmware guarda la sesión LoRaWAN en la partición de
flash `PARAMETER_1`:

- `node.getBufferSession()` y `node.getBufferNonces()` devuelven punteros a los buffers internos de
  RadioLib que contienen la sesión y los contadores (nonces).
- `saveSession()` escribe ambos buffers en flash.
- `loadSession()` los lee de vuelta y los inyecta con `setBufferNonces()` / `setBufferSession()`
  **antes** de llamar a `activateOTAA()`.

RadioLib reconoce la sesión restaurada y devuelve `RADIOLIB_LORAWAN_SESSION_RESTORED`, en lugar de
ejecutar un join completo. Esto evita el consumo de `DevNonce`/`JoinNonce` y acelera el arranque.

### 3.4 Heartbeat y ventana RX

Cada **30 segundos** (`HEARTBEAT_MS = 30000`) el nodo envía un uplink de 1 byte (`0xBB`) en el puerto
**1** (puerto de aplicación). Al tratarse de un dispositivo **Clase A**, este uplink abre dos
ventanas de recepción (**RX1** y **RX2**) durante las cuales el servidor puede enviar un downlink.

Si el servidor responde, el firmware lo muestra:

```
[HEARTBEAT] downlink recibido:
[DOWNLINK] 48 4F 4C 41 -> "HOLA"
```

### 3.5 Uplink manual

Escribiendo una secuencia HEX seguida de `Enter` en el monitor serial, el nodo la envía como uplink
en el puerto 1:

```
DE AD BE EF<Enter>
>> Enviando: DE AD BE EF
-> OK (sin downlink)
```

También acepta el formato compacto sin espacios (`DEADBEEF`).

### 3.6 Comando ERASE

Escribiendo `ERASE` (mayúsculas o minúsculas) se borra la sesión persistida en flash y se reinicia
el micro. Es útil cuando el Network Server ha sido reiniciado y el join falla por conflicto de
`JoinNonce`/`DevNonce`.

---

## 4. Forma de operar (instrucciones de uso)

1. **Registrar el dispositivo** en el Network Server / gateway con las credenciales de
   `credentials.h` (ver [sección 8](#8-configuración-lorawan)).
2. **Conectar la antena** al conector U.FL/IPEX (¡obligatorio antes de energizar!).
3. **Conectar el USB** (CP2102) al PC.
4. **Abrir el monitor serial** a **9600 baud 8N1**.
5. **Observar** el arranque y el join (o la restauración de sesión).
6. **Esperar** el heartbeat cada 30 s y los downlinks entrantes.
7. **Para enviar un uplink manual**: escribir HEX + `Enter` (ej. `DE AD BE EF`).
8. **Para borrar la sesión** (reinicio del NS, cambio de identidad, etc.): escribir `ERASE`.

> 💻 **Alternativa gráfica:** en lugar del monitor serial puedes usar la aplicación de escritorio
> `cubecell_gui.py` (auto-detección de puerto, uplinks HEX/ASCII, downlinks y ERASE con un clic).
> Ver la sección 14 *Aplicación de escritorio* más abajo.

---

## 5. Tabla de pines (pinout)

> Los pines de la radio **SX1262** y de la UART son **internos** del CubeCell y **no son accesibles
> por el usuario** a través de pines expuestos. Se documentan por referencia de cableado interno.

### 5.1 Pines de la radio SX1262

| Señal | GPIO (ASR6502) | Función |
|-------|----------------|---------|
| **NSS** (CS) | `35` | Chip select SPI |
| **DIO1** | `38` | Interrupción de la radio (TX/RX done) |
| **RST** | `47` | Reset de la radio |
| **BUSY** | `39` | Señal de ocupado de la radio |

> En el código: `Module mod(35, 38, 47, 39); // NSS, DIO1, RST, BUSY`

### 5.2 UART / USB

| Señal | Conexión | Nota |
|-------|----------|------|
| **UART0 TX** | CP2102 → USB | Transmisión serial |
| **UART0 RX** | CP2102 → USB | Recepción serial |
| **USB** | Conector micro-USB | Alimentación 5 V + datos |

### 5.3 Alimentación

| Pin | Valor | Nota |
|-----|-------|------|
| **VDD** | 3.3 V | Alimentación del módulo (regulada internamente desde 5 V USB) |
| **GND** | 0 V | Referencia común |

---

## 6. Diagrama de conexión

### 6.1 Conexión física (descripción textual)

```
                       Heltec CubeCell HTCC-AB01
       +-----------------------------------------------------+
       |                                                     |
       |   [USB micro]  <=== cable USB ===>  PC (CP2102)     |
       |                                                     |
       |   [Antena U.FL] <=== pigtail / antena externa       |
       |                                                     |
       |   ASR6502 (MCU)            SX1262 (radio)           |
       |     GPIO35  NSS  ----------->  NSS  (SPI CS)        |
       |     GPIO38  DIO1 <-----------  DIO1 (IRQ)           |
       |     GPIO47  RST  ----------->  RESET                |
       |     GPIO39  BUSY <-----------  BUSY                 |
       |     SPI MOSI/MISO/SCK <======> SPI (no expuestos)   |
       |                                                     |
       |   UART0 TX/RX  <==========>  CP2102 <==> USB <==> PC|
       +-----------------------------------------------------+
```

### 6.2 Flujo de señales

```
[PC / Serial Monitor]  --UART 9600-->  [ASR6502 MCU]  --SPI-->  [SX1262]  ~~~ LoRa 868/915 ~~~
                                                                        |
                                                                        v
                                                          [Gateway LoRaWAN] --> [Network Server]
```

- **UART0** conecta el MCU con el PC a través del CP2102 (USB).
- **SPI** conecta el MCU con el SX1262 (MOSI/MISO/SCK internos).
- **DIO1** notifica al MCU eventos de la radio (final de TX, apertura de RX, recepción).
- **BUSY** impide que el MCU hable con la radio mientras ésta ejecuta comandos.
- **RST** permite reiniciar la radio de forma controlada.

> La antena debe conectarse al conector **U.FL/IPEX** de la placa. **No energizar sin antena**:
> transmitir sin carga puede dañar el PA del SX1262.

---

## 7. Formato de payload

### 7.1 Uplink (dispositivo → servidor)

| Byte(s) | Campo | Descripción | Endianidad |
|---------|-------|-------------|------------|
| `0` | `type` | `0xBB` para heartbeat; valor libre en modo manual | — |

- **Heartbeat**: payload fijo de 1 byte `0xBB` en el **puerto 1**.
- **Uplink manual**: los bytes HEX que escribas (hasta `MAX_PAYLOAD = 51` bytes) en el **puerto 1**.

### 7.2 Downlink (servidor → dispositivo)

| Byte(s) | Campo | Descripción |
|---------|-------|-------------|
| `0..n` | `data` | Bytes enviados por el servidor (típicamente texto ASCII) |

El firmware muestra cada byte en HEX y su interpretación ASCII (los caracteres no imprimibles se
representan como `.`):

```
[DOWNLINK] 48 4F 4C 41 -> "HOLA"
```

### 7.3 Decoder sugerido (TTN / ChirpStack)

No hay un decoder específico en este repositorio. Para TTN/ChirpStack puedes usar un decoder
mínimo que interprete el heartbeat y los bytes ASCII:

```javascript
// decoder.js — ejemplo para CubeCell-LoRaWAN-Demo
function decodeUplink(input) {
  var bytes = input.bytes;
  var data = {};

  // Heartbeat 0xBB
  if (bytes.length === 1 && bytes[0] === 0xBB) {
    data.type = "heartbeat";
  } else {
    data.type = "manual";
    // Intenta interpretar como texto ASCII
    var txt = "";
    for (var i = 0; i < bytes.length; i++) {
      txt += String.fromCharCode(bytes[i]);
    }
    data.text = txt;
  }

  data.port = input.fPort;
  return { data: data };
}

// Opcional: codificar un downlink ASCII para enviar al nodo
function encodeDownlink(input) {
  var str = (input.data && input.data.text) ? input.data.text : "OK";
  var bytes = [];
  for (var i = 0; i < str.length; i++) {
    bytes.push(str.charCodeAt(i));
  }
  return { bytes: bytes, fPort: 1 };
}
```

---

## 8. Configuración LoRaWAN

### 8.1 Credenciales (credentials.h vs credentials.example.h)

- **`credentials.h`** — contiene las credenciales **reales** (JoinEUI, DevEUI, AppKey, NwkKey).
  Está **ignorado por git** (`.gitignore`). **No subir a repositorios públicos.**
- **`credentials.example.h`** — plantilla segura con valores a cero. Para compartir el proyecto,
  copia esta plantilla a `credentials.h` y completa tus valores.

Para generar tu propia identidad:

1. Copia la plantilla:
   ```bash
   cp credentials.example.h credentials.h
   ```
2. Edita `credentials.h` con tus valores de JoinEUI, DevEUI, AppKey (y NwkKey = AppKey en 1.0.x).

### 8.2 Registro del dispositivo en el Network Server

Según tu Network Server:

**The Things Network (TTN) / The Things Stack:**

1. Entra a la consola y crea una **aplicación**.
2. **Registrar dispositivo manualmente**.
3. Introduce: **DevEUI**, **JoinEUI (AppEUI)** y **AppKey** (coinciden con `credentials.h`).
4. Selecciona el plan de frecuencias **AU915-928** (sub-banda 2) para el *frequency plan*.
5. Guarda. El dispositivo deberá poder unirse (join).

**ChirpStack (open source):**

1. Crea un **device profile** con región **AU915** (sub-banda 2) y Clase A.
2. Crea la **aplicación** y añade el dispositivo con **OTAA**: DevEUI + JoinEUI + AppKey.
3. Configura el *service profile* y el *gateway*.

**Helium:**

1. Crea un device con el **DevEUI** en la console de Helium.
2. Usa la integración correspondiente (ej. ChirpStack o Helium Console) e introduce JoinEUI/AppKey.
3. AU915 es compatible; verifica la sub-banda.

**Milesight (gateway embebido con NS):**

1. En la web UI del gateway (ej. UG56), crea una **red LoRaWAN** en región **AU915 sub-banda 2**.
2. Añade el dispositivo con **OTAA** usando DevEUI + JoinEUI + AppKey.
3. Habilita el **Network Server embebido** del gateway.

### 8.3 Región y sub-banda del gateway

- **Región:** AU915 (Australia 915–928 MHz).
- **Sub-banda:** **2** (configurada en el código con `subBand = 2`).
- Asegúrate de que el **gateway** esté configurado para **AU915** y que el plan de frecuencias del
  Network Server use la **sub-banda 2** (o que el gateway escuche todas las sub-bandas).

### 8.4 Pegar el decoder.js en el Network Server

1. Copia el contenido del bloque `decoder.js` de la [sección 7.3](#73-decoder-sugerido-ttn--chirpstack).
2. En **TTN**: Aplicación → *Payload formatters* → *Uplink* → *Javascript* → pega y guarda.
3. En **ChirpStack**: Device profile → *Codec* → *Custom JavaScript* → pega el decoder.
4. Para downlinks: en TTN usa *Downlink* formatter con `encodeDownlink`.

---

## 9. Instrucciones de compilación y carga

### 9.1 Requisitos previos

1. Instalar **Arduino CLI**:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh
   ```
2. Instalar el **core de Heltec CubeCell** (ASR650x):
   ```bash
   arduino-cli config add board_manager.additional_urls \
     https://resource.heltec.cn/download/package_CubeCell_index.json
   arduino-cli core update-index
   arduino-cli core install CubeCell:CubeCell
   ```
3. Instalar **RadioLib 7.7.1**:
   ```bash
   arduino-cli lib install "RadioLib@7.7.1"
   ```
4. Crear `credentials.h` (ver [sección 8.1](#81-credenciales-credentialsh-vs-credentialsexampleh)).

### 9.2 Compilar

```bash
cd /home/jma/Documents/Proyects/OpenCode/AG.CreadorContenido/proyectos/CubeCell-LoRaWAN-Demo

# Compilar
arduino-cli compile --fqbn CubeCell:CubeCell:CubeCell-Board .
```

### 9.3 Transferir a la placa

```bash
# Conecta el CubeCell por USB (CP2102) y comprueba el puerto
arduino-cli board list

# Transferir (ajusta /dev/ttyUSB0 a tu puerto)
arduino-cli upload -p /dev/ttyUSB0 --fqbn CubeCell:CubeCell:CubeCell-Board .
```

### 9.4 Monitor serial

```bash
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=9600
```

---

## 10. Ejemplos de uso realistas

### 10.1 Arranque y join (primera vez)

```
========================================
  CubeCell LoRaWAN Demo (aislado)
  AU915 | OTAA | Clase A
========================================
Radio OK
Node OK
Verificando sesion persistida...
+++ JOINED +++
[PERSIST] Sesion guardada en flash
----------------------------------------
Heartbeat cada 30 s. Serial 9600 8N1.
Modo manual: escribe HEX + Enter -> uplink.
Comando ERASE: borra la sesion y reinicia.
>
```

### 10.2 Arranque con sesión restaurada (sin re-join)

```
========================================
  CubeCell LoRaWAN Demo (aislado)
  AU915 | OTAA | Clase A
========================================
Radio OK
Node OK
Verificando sesion persistida...
+++ SESION RESTAURADA (sin re-join) +++
----------------------------------------
Heartbeat cada 30 s. Serial 9600 8N1.
Modo manual: escribe HEX + Enter -> uplink.
Comando ERASE: borra la sesion y reinicia.
>
```

### 10.3 Heartbeat con downlink recibido

```
[HEARTBEAT] downlink recibido:
[DOWNLINK] 48 4F 4C 41 -> "HOLA"
>
```

### 10.4 Uplink manual

```
DE AD BE EF
>> Enviando: DE AD BE EF
-> OK (sin downlink)
>
```

Con downlink de respuesta:

```
CA FE
>> Enviando: CA FE
-> OK + downlink (4 bytes)
[DOWNLINK] 4F 4B 21 21 -> "OK!!"
>
```

### 10.5 Borrado de sesión

```
ERASE
[ERASE] Sesion borrada. Reiniciando...
========================================
  CubeCell LoRaWAN Demo (aislado)
  ...
+++ JOINED +++
[PERSIST] Sesion guardada en flash
...
>
```

---

## 11. Advertencias y precauciones

| Riesgo | Detalle |
|--------|---------|
| ⚠️ **Antena** | **No energices la placa sin antena conectada.** Transmitir sin carga puede dañar el amplificador de potencia del SX1262. |
| ⚠️ **Alimentación 3.3 V** | El módulo opera a 3.3 V. No alimentes directamente con 5 V en los pines de alimentación (el USB ya regula a 3.3 V). Respeta la polaridad. |
| ⚠️ **DevNonce / JoinNonce** | Si reinicias el **Network Server**, el `JoinNonce` del servidor se resetea y el dispositivo, con `DevNonce` antiguo, puede recibir `JOIN_NONCE_INVALID` (-1116). Solución: enviar `ERASE` para borrar la sesión y re-enrolar. |
| ⚠️ **Credenciales** | No subas `credentials.h` a repositorios públicos. Usa `credentials.example.h` como plantilla. |
| ⚠️ **Duty cycle / sub-banda** | Respeta la sub-banda 2 de AU915 y el *duty cycle* legal. No envíes a más frecuencia de la permitida. |
| ⚠️ **Región** | Este firmware está fijado a **AU915 sub-banda 2**. Para otra región hay que recompilar (ver `docs/developer.md`). |
| ⚠️ **RadioLib 7.7.1** | Usa exactamente RadioLib 7.7.1; otras versiones pueden tener APIs distintas para `beginOTAA`/`getBufferSession`. |

---

## 12. Estructura del repositorio

```
CubeCell-LoRaWAN-Demo/
├── CubeCell-LoRaWAN-Demo.ino   # Firmware principal
├── cubecell_gui.py             # Panel de control de escritorio (PyQt6)
├── requirements.txt            # Dependencias de la GUI (pyserial, PyQt6)
├── credentials.h               # Credenciales reales (gitignored)
├── credentials.example.h       # Plantilla de credenciales
├── .gitignore                  # Excluye credentials.h, build, __pycache__, etc.
├── README.md                   # Este archivo
└── docs/
    ├── datasheet.md            # Documentación de usuario / especificaciones
    ├── developer.md            # Documentación de desarrollo
    └── gui_cubecell.md         # Guía de usuario de la aplicación de escritorio
```

---

## 13. Documentación adicional

- **[docs/datasheet.md](docs/datasheet.md)** — documentación de usuario, especificaciones técnicas y
  guía de solución de problemas.
- **[docs/developer.md](docs/developer.md)** — explicación del código, persistencia de sesión y guía
  de modificación.
- **[docs/gui_cubecell.md](docs/gui_cubecell.md)** — guía de usuario de la aplicación de escritorio
  (`cubecell_gui.py`).

---

## 14. Aplicación de escritorio (GUI) — `cubecell_gui.py`

> Panel de control estilo RAF trasladado a la red LoRaWAN: permite operar el nodo CubeCell desde el
> PC sin usar el monitor serial, con terminal en vivo, uplinks HEX/ASCII, downlinks e indicadores.

### 14.1 Características

- **Terminal en vivo** coloreado (banner, join, restauración, heartbeat, downlinks, ecos de uplink).
- **Uplink manual**: modo **HEX** (`DE AD BE EF` o `DEADBEEF`) o **ASCII** (texto → Latin-1);
  respeta `MAX_PAYLOAD = 51` bytes.
- **Downlinks**: cada `[DOWNLINK] XX XX -> "texto"` se lista con timestamp, HEX y texto.
- **Indicadores**: sesión (JOINED/RESTAURADA/SIN JOIN), radio, heartbeats, uplinks, downlinks,
  bytes RX/TX.
- **ERASE** con confirmación (borra sesión y reinicia el nodo).
- **Auto-detección de puerto**: sondea los puertos USB y selecciona el CubeCell automáticamente
  (envía una sonda inofensiva `x` y comprueba la respuesta `?? Error: escribe hex valido`).

### 14.2 Requisitos e instalación

```bash
pip install -r requirements.txt        # pyserial >= 3.5, PyQt6 >= 6.4
```

En Linux añade tu usuario al grupo `dialout` para acceder al puerto serie:

```bash
sudo usermod -aG dialout $USER
# re-loguear la sesión
```

### 14.3 Ejecutar

```bash
cd CubeCell-LoRaWAN-Demo
python3 cubecell_gui.py
```

### 14.4 Uso básico

1. La app detecta el puerto del CubeCell (en esta instalación: **`/dev/ttyUSB1`**; el otro CP210x es
   el bridge ESP-NOW). Verifica el desplegable y usa **⟳ Scan** si hace falta.
2. Pulsa **Conectar** (9600 8N1).
3. Para enviar: escribe HEX o activa **ASCII**, pulsa **Enviar**.
4. Observa el eco del firmware: `>> Enviando: DE AD BE EF -> OK (sin downlink)`.
5. Los downlinks aparecen en su tarjeta: `13:07:35  4F 4B 21 21 → "OK!!"`.
6. **Borrar sesión** → confirma → el firmware responde `[ERASE] Sesion borrada. Reiniciando...`.

### 14.5 Ejemplo de sesión real

```
--- Conectado a /dev/ttyUSB1 @ 9600 8N1 (13:06:41) ---
[GUI] Enviando (HEX): DE AD BE EF
>> Enviando: DE AD BE EF -> OK (sin downlink)
>
```

### 14.6 Documentación de la GUI

- **[docs/gui_cubecell.md](docs/gui_cubecell.md)** — guía de usuario detallada (pantalla, ejemplos,
  solución de problemas, protocolo serial).
- **[docs/developer.md](docs/developer.md)** (sección "Aplicación de escritorio") — arquitectura
  interna (hilo lector, clasificador de líneas, función `probe_cubecell()`) y guía de extensión.
