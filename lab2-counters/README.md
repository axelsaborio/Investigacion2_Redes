# Laboratorio 2 - Contadores y estadísticas de tráfico

Sistema de monitoreo de tráfico implementado en el plano de datos con P4, BMv2 y Mininet.

## Objetivo

Medir el tráfico que atraviesa un switch programable y consultar las estadísticas desde un controlador en Python:

- Contadores directos por flujo (IP origen + IP destino).
- Contadores globales por protocolo: TCP, UDP, ICMP y otros.
- Registro del tamaño de los paquetes mediante registers.
- Controlador Python que lee los contadores al menos cada 5 segundos.
- Detección de flujos elefante con un umbral configurable de bytes.

## Estructura

```text
lab2-counters/
├── counters.p4               Programa P4 del switch
├── topology.py               Topología de Mininet (1 switch, 4 hosts)
├── controller.py             Controlador de estadísticas (Thrift)
├── tables/
│   └── s1.txt                Entradas de las tablas y umbral inicial
├── scripts/
│   ├── pruebas.sh            Verificaciones del laboratorio
│   └── generar_trafico.py    Generador de tráfico con Scapy
├── build/                    Archivos generados por el compilador
└── README.md
```

## Estado

En desarrollo.
