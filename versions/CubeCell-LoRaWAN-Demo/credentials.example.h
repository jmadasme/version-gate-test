/*
 * credentials.example.h — PLANTILLA de credenciales OTAA LoRaWAN
 * ================================================================
 * Renombra este archivo a `credentials.h` y completa tus credenciales.
 *
 * AU915 sub-banda 2 | OTAA Clase A
 */

#ifndef CREDENTIALS_H
#define CREDENTIALS_H

#include <stdint.h>

// JoinEUI / AppEUI (LSB primero en RadioLib)
uint64_t joinEui = 0x0000000000000000;

// DevEUI de tu dispositivo
uint64_t devEui = 0x0000000000000000;

// AppKey (16 bytes)
uint8_t appKey[] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

// NwkKey (16 bytes)
uint8_t nwkKey[] = { 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
                     0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00 };

#endif // CREDENTIALS_H
