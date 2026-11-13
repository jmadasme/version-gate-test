# Guía de usuario — `cubecell_gui.py`

> **Panel de control de escritorio (GUI)** para operar el nodo **Heltec CubeCell HTCC-AB01**
> (LoRaWAN · OTAA Clase A · AU915 sub-banda 2) conectado por USB (CP2102).
>
> Alternativa gráfica al monitor serial clásico (`arduino-cli monitor`). Recibe y envía datos
> hacia/desde el gateway LoRaWAN (p. ej. **Milesight UG56**).

---

## 1. ¿Qué hace la aplicación?

| Función | Descripción |
|---------|-------------|
| **Terminal en vivo** | Log coloreado del serial del nodo: banner, join, restauración de sesión, heartbeat, downlinks y respuestas de uplink. |
| **Uplink manual** | Envía bytes por LoRaWAN (puerto 1) escribiendo HEX o activando modo ASCII. |
| **Recepción de downlinks** | Cada `[DOWNLINK] XX XX -> "texto"` se lista con timestamp, HEX y texto ASCII. |
| **Indicadores** | Sesión (JOINED / RESTAURADA / SIN JOIN), estado de la radio, contadores de heartbeats, uplinks, downlinks y bytes RX/TX. |
| **Comando ERASE** | Borra la sesión persistida en flash y reinicia el nodo (con confirmación). |
| **Auto-detección de puerto** | Sondea los puertos USB y selecciona automáticamente el del CubeCell. |

## 2. Requisitos

- Python **3.9+**.
- Dependencias: `pyserial` y `PyQt6`.

```bash
pip install -r requirements.txt
# o directamente:
pip install pyserial PyQt6
```

- El nodo CubeCell conectado por USB (el sistema debe ver el CP2102 como `/dev/ttyUSB*`).
- Permisos de lectura/escritura sobre el puerto serie (en Linux: pertenecer al grupo `dialout`).

## 3. Cómo ejecutarla

```bash
cd CubeCell-LoRaWAN-Demo
python3 cubecell_gui.py
```

Al abrir:

1. La app **detecta automáticamente el puerto del CubeCell** (sonda inofensiva: envía `x` y
   comprueba que el firmware responda `?? Error: escribe hex valido`). El puerto correcto aparece
   seleccionado en el desplegable.
2. Pulsa **Conectar** (o **Conectar/Desconectar**).
3. Espera el banner del nodo (si acaba de conectarse/reiniciarse) y observa el heartbeat cada 30 s.

> **Nota sobre el puerto:** en esta instalación el CubeCell es `/dev/ttyUSB1` y el otro CP210x
> (bridge ESP-NOW) es `/dev/ttyUSB0`. No asumas que es siempre `ttyUSB0`: usa el botón **⟳ Scan**
> o la auto-detección. Si tienes el nodo en otro puerto, selecciónalo manualmente en el desplegable.

## 4. Pantalla principal

```
┌──────────────────────────────────────────────────────────────────────┐
│  RAF · Red Autogestionada Fractal        Panel CubeCell LoRaWAN      │
│  ┌─ Puerto ───────┐ ┌ Conectar ┐ ┌⟳ Scan┐ ┌─ Modo ──┐ ┌ Borrar sesión┐ │
│  │ /dev/ttyUSB1 · │ │  ● Conectar │ │  │  │ ⬡ HEX  ◉ │ │  (ERASE)     │ │
│  └────────────────┘ └──────────┘ └──────┘ │ ⬢ ASCII │ └──────────────┘ │
│  ┌─ Indicadores ──────────────────────────┐                             │
│  │ Sesión —   Radio —   HB 0   UL 0  DL 0│  ┌─ Downlinks ──────────┐  │
│  │ RX 0 B · TX 0 B · 12:00:00            │  │ 12:00:01 48 4F → "HOLA"│ │
│  └────────────────────────────────────────┘  └───────────────────────┘ │
│  ┌─ Terminal (log serial en vivo) ────────────────────────────────┐   │
│  │ >> Enviando: DE AD BE EF -> OK (sin downlink)                  │   │
│  │ >                                                              │   │
│  └────────────────────────────────────────────────────────────────┘   │
│  ┌─ Uplink ──────────────────────┐ [ Enviar ]                          │
│  │ [ DE AD BE EF              ]  │                                     │
│  └───────────────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.1 Zona de puerto y conexión

- **Desplegable de puertos**: lista los `/dev/ttyUSB*`, `/dev/ttyACM*` y dispositivos USB visibles.
- **⟳ Scan**: re-detecta puertos y vuelve a sondear (auto-selección del CubeCell).
- **Conectar/Desconectar**: abre o cierra el puerto a **9600 8N1**.

### 4.2 Zona de envío (uplink)

- **Modo HEX** (por defecto): escribe bytes en hexadecimal, con o sin espacios (`DE AD BE EF` o
  `DEADBEEF`). Máximo **51 bytes** (igual al firmware `MAX_PAYLOAD`).
- **Modo ASCII**: escribe texto plano y se convierte a bytes Latin-1 antes de enviar.
- **Enviar**: transmite por el puerto. El firmware hará el uplink LoRaWAN y la app mostrará el eco
  `>> Enviando: ... -> OK (sin downlink)` (o `-> OK + downlink (n bytes)` si el servidor responde).

### 4.3 Zona de indicadores

| Indicador | Qué muestra |
|-----------|-------------|
| **Sesión** | `JOINED ✓` (join OTAA), `RESTAURADA` (sesión desde flash), `SIN JOIN` (fallo). |
| **Radio** | `OK ✓` si `Radio OK`, `FALLO` si `Radio init FAILED: n`. |
| **HB** | Número de heartbeats que recibieron downlink (el firmware solo imprime el heartbeat si llega downlink). |
| **UL** | Uplinks manuales enviados (eco `>> Enviando:` del firmware). |
| **DL** | Downlinks recibidos (`[DOWNLINK]`). |
| **RX / TX** | Bytes brutos recibidos/transmitidos por el puerto serie. |

### 4.4 Zona de downlinks

Cada downlink se añade como: `HH:MM:SS  <HEX> → "<texto ASCII>"`.

### 4.5 Zona de terminal

- Log coloreado del serial (mismas líneas que el monitor serial).
- **Colores**: teal = envíos/eco, verde = OK/downlinks/join, rojo = errores/fail, azul = heartbeats,
  gris = prompt e información, `>> Enviando:` en negrita teal.
- La línea de prompt `> ` del firmware se muestra como línea separada (detección del prompt sin
  newline, sin partir las líneas que contienen `-> `).

## 5. Ejemplos de uso realistas

### 5.1 Conexión + uplink manual (HEX)

```
--- Conectado a /dev/ttyUSB1 @ 9600 8N1 (13:06:41) ---
[GUI] Enviando (HEX): DE AD BE EF
>> Enviando: DE AD BE EF -> OK (sin downlink)
>
```

### 5.2 Uplink con downlink de respuesta del servidor

```
[GUI] Enviando (HEX): CA FE
>> Enviando: CA FE -> OK + downlink (4 bytes)
[DOWNLINK] 4F 4B 21 21 -> "OK!!"
>
```

La tarjeta de downlinks muestra:

```
13:07:35  4F 4B 21 21  →  "OK!!"
```

### 5.3 Modo ASCII

1. Marca **⬢ ASCII**.
2. Escribe `HOLA` y pulsa **Enviar**.
3. El firmware recibe `48 4F 4C 41` y lo envía por LoRaWAN:

```
[GUI] Enviando (ASCII): HOLA
>> Enviando: 48 4F 4C 41 -> OK (sin downlink)
>
```

### 5.4 Sesión restaurada (solo arranque del nodo)

Si el nodo ya tiene sesión persistida, al reiniciarlo la app muestra:

```
Radio OK
Node OK
Verificando sesion persistida...
+++ SESION RESTAURADA (sin re-join) +++
...
>
```

### 5.5 Borrar sesión (ERASE)

1. Pulsa **Borrar sesión** y confirma el diálogo.
2. La app envía `ERASE`; el firmware responde `[ERASE] Sesion borrada. Reiniciando...` y el nodo
   vuelve a hacer join OTAA desde cero.

## 6. Solución de problemas

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| "Sin conexión serial" al enviar | No hay puerto abierto | Pulsa **Conectar** primero. |
| El desplegable no encuentra el puerto | Falta permiso o el cable no está | `ls /dev/ttyUSB*`; añade tu usuario a `dialout`: `sudo usermod -aG dialout $USER` (re-loguear). |
| Se conecta pero no aparece el banner | El nodo lleva encendido mucho tiempo (el banner solo sale al arrancar) | Envía un uplink; verás el eco `>> Enviando:`. |
| "?? Error: escribe hex valido" | Escribiste HEX inválido / modo ASCII con caracteres no Latin-1 | Revisa el formato (pares de dígitos 0-9A-F) o usa modo ASCII para texto. |
| Nada en pantalla al conectar al puerto equivocado | El otro CP210x (bridge ESP-NOW @115200) no responde a 9600 | Usa **⟳ Scan** o selecciona el puerto del CubeCell manualmente. |
| `Join FAILED: ...` / `SIN JOIN` | Credenciales, región/sub-banda o NS reiniciado | Verifica `credentials.h` y la sub-banda 2 de AU915; pulsa **ERASE** si el NS fue reiniciado (conflicto de nonces). |
| La app no abre (ImportError) | Faltan `pyserial` o `PyQt6` | `pip install -r requirements.txt`. |

## 7. Protocolo serial del firmware (referencia rápida)

| Línea del nodo | Significado |
|----------------|-------------|
| `>> Enviando: XX XX` | El nodo envía un uplink (eco del envío manual). |
| `-> OK (sin downlink)` | Uplink confirmado; el NS no respondió. |
| `-> OK + downlink (n bytes)` | Uplink confirmado con respuesta del NS. |
| `-> ERROR n (texto)` | Error de radio/red (ver `docs/developer.md`). |
| `[DOWNLINK] XX XX -> "texto"` | Downlink recibido, en HEX + ASCII. |
| `[HEARTBEAT] downlink recibido:` | Heartbeat de 30 s que recibió downlink. |
| `[ERASE] Sesion borrada. Reiniciando...` | Comando ERASE ejecutado. |
| `[REJOIN] +++ EXITOSO +++` / `+++ SESION RESTAURADA +++` | Re-join tras fallo / sesión recuperada. |
| `?? Error: escribe hex valido` | Entrada no-HEX detectada por el firmware. |
| `> ` | Prompt: el nodo está listo para recibir comandos. |

---

*Documento de usuario de `cubecell_gui.py`. Para la arquitectura interna y guía de desarrollo, ver
[developer.md](developer.md) (sección "Aplicación de escritorio").*