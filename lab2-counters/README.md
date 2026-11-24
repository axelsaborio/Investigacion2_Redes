# Laboratorio 2 - Contadores y estadísticas de tráfico

Sistema de monitoreo de tráfico implementado en el plano de datos con P4, BMv2 y Mininet.

El switch reenvía paquetes IPv4 entre cuatro hosts y, mientras lo hace, mide el tráfico. Un controlador en Python consulta esas mediciones por Thrift y las muestra en la terminal.

## Funcionalidades

| Requisito | Implementación |
|---|---|
| Contadores directos por flujo | `direct_counter flow_counter` asociado a la tabla `flow_stats` (llave: IP origen + IP destino) |
| Contadores globales por protocolo | `counter proto_counter` con 4 índices: TCP, UDP, ICMP y otros |
| Registro del tamaño de los paquetes | Registers `flow_bytes`, `flow_pkt_min`, `flow_pkt_max` (por flujo) y `size_hist` (histograma global) |
| Controlador Python | `controller.py` lee contadores y registers con `simple_switch_CLI` (Thrift) cada 5 segundos o menos |
| Detección de flujos elefante | Umbral configurable en el register `elephant_threshold`; el switch marca el flujo en `flow_elephant` y el controlador muestra la alerta |

## Topología

```text
               h1 (10.0.0.1)
                |
                | puerto 1
 h2 ---------- s1 ---------- h3
 (10.0.0.2)  2 |  3       (10.0.0.3)
                | puerto 4
               h4 (10.0.0.4)
```

| Host | Dirección IP | MAC | Puerto de s1 |
|------|-------------|-----|--------------|
| h1 | 10.0.0.1/24 | 00:00:00:00:00:01 | 1 |
| h2 | 10.0.0.2/24 | 00:00:00:00:00:02 | 2 |
| h3 | 10.0.0.3/24 | 00:00:00:00:00:03 | 3 |
| h4 | 10.0.0.4/24 | 00:00:00:00:00:04 | 4 |

- Los cuatro hosts están en la misma subred, así que no hace falta enrutamiento: el switch reenvía según la IP destino.
- Las entradas ARP son estáticas y IPv6 está desactivado en los hosts. Así, todo el tráfico que miden los contadores es el que generan las pruebas.
- El switch escucha comandos Thrift en el puerto 9090.

## Estructura

```text
lab2-counters/
├── counters.p4                 Programa P4 del switch
├── topology.py                 Topología de Mininet (1 switch, 4 hosts)
├── controller.py               Controlador de estadísticas (Thrift)
├── tables/
│   └── s1.txt                  Entradas de las tablas y umbral inicial
├── scripts/
│   ├── pruebas.sh              Verificaciones y pruebas del laboratorio
│   ├── generar_trafico.py      Generador de tráfico con Scapy
│   └── prueba_automatica.py    Las 6 pruebas de extremo a extremo
├── resultados_pruebas.txt      Salida de la última ejecución de las pruebas
├── build/                      Archivos generados por el compilador
└── README.md
```

## Funcionamiento del programa P4

Cada paquete que entra al switch pasa por estos pasos (bloque `MyIngress`):

1. **Contador por protocolo.** Se revisa el campo `protocol` de IPv4 (6 = TCP, 17 = UDP, 1 = ICMP) y se incrementa el índice correspondiente de `proto_counter`. Lo demás (por ejemplo, el protocolo IP 253 o una trama que no es IPv4) cuenta como "otros".
2. **Histograma de tamaños.** Según `standard_metadata.packet_length`, el paquete suma 1 en una de cuatro categorías del register `size_hist`: 0–127 B, 128–511 B, 512–1023 B y 1024 B o más.
3. **Contador directo por flujo.** Se aplica la tabla `flow_stats` con llave IP origen + IP destino. Cada entrada tiene su propio contador de paquetes y bytes (`flow_counter`). La acción `count_flow` guarda además el identificador del flujo.
4. **Registers del flujo.** Con ese identificador se actualizan los bytes acumulados (`flow_bytes`) y los tamaños mínimo y máximo de paquete del flujo.
5. **Flujo elefante.** Si los bytes acumulados superan el valor de `elephant_threshold`, el switch escribe 1 en `flow_elephant` para ese flujo.
6. **Reenvío.** La tabla `ipv4_forward` asigna el puerto de salida según la IP destino. Si no hay entrada, el paquete se descarta.

¿Por qué hay un register de bytes si el direct counter ya cuenta bytes? Los contadores solo los puede leer el plano de control: el programa P4 no puede consultar su valor. Para que el switch compare los bytes del flujo con el umbral, necesita un register, que sí se puede leer y escribir desde el plano de datos.

Las entradas de las tablas y el umbral inicial (100 000 bytes) están en `tables/s1.txt`. `topology.py` las carga al iniciar. Se monitorean los 12 flujos posibles entre los cuatro hosts.

## Requisitos

- Ubuntu 24.04 LTS
- P4C (`p4c-bm2-ss`)
- BMv2 (`simple_switch` y `simple_switch_CLI`)
- Mininet 2.3.0
- Python 3 con Scapy
- iperf3 y ethtool (opcional, para tráfico TCP real)

## Compilación

Desde la raíz del repositorio:

```bash
mkdir -p lab2-counters/build

p4c-bm2-ss --arch v1model \
-o lab2-counters/build/counters.json \
lab2-counters/counters.p4
```

## Ejecución

Se usan dos terminales, ambas en la raíz del repositorio.

**Terminal 1: topología**

```bash
sudo mn -c
sudo python3 lab2-counters/topology.py
```

**Terminal 2: controlador**

```bash
python3 lab2-counters/controller.py --reset
```

Opciones del controlador:

| Opción | Descripción |
|---|---|
| `--intervalo N` | Segundos entre lecturas, máximo 5 (por defecto 5) |
| `--umbral B` | Umbral de flujo elefante en bytes (por defecto 100000) |
| `--reset` | Pone en cero contadores y registers al iniciar |
| `--una-vez` | Hace una sola lectura y termina |
| `--todos` | Muestra también los flujos sin tráfico |
| `--sin-limpiar` | No limpia la pantalla entre lecturas |

Las alertas de flujo elefante se muestran en la terminal y también se guardan en `lab2-counters/elefantes.log`.

## Generación de tráfico

`generar_trafico.py` se ejecuta dentro de un host de Mininet. Crea paquetes con Scapy de un tamaño exacto (en bytes de trama Ethernet), que es justo lo que mide el switch.

Dentro de la consola de Mininet:

```bash
# 10 paquetes de cada protocolo (TCP, UDP, ICMP y otros)
h1 python3 lab2-counters/scripts/generar_trafico.py --destino 10.0.0.2 --tipo mixto

# Volumen conocido: 100 paquetes UDP de 1000 bytes = 100 000 bytes
h3 python3 lab2-counters/scripts/generar_trafico.py --destino 10.0.0.4 --tipo udp --cantidad 100 --tamano 1000

# Flujo elefante de 150 000 bytes
h1 python3 lab2-counters/scripts/generar_trafico.py --destino 10.0.0.3 --tipo elefante --bytes 150000
```

También se puede usar iperf3 para generar tráfico TCP real:

```bash
h3 iperf3 -s -D
h1 iperf3 -c 10.0.0.3 -n 300K
```

El host destino puede responder: eco ICMP, TCP RST o ICMP de "puerto inalcanzable". Esas respuestas pertenecen al flujo inverso (destino → origen). Por eso, el flujo origen → destino tiene exactamente lo que envió el script.

## Pruebas

### Verificaciones iniciales

```bash
./lab2-counters/scripts/pruebas.sh
```

Compila el programa y revisa que existan los 8 contadores y registers en el JSON compilado. También comprueba la sintaxis de los programas Python y que haya 4 entradas de reenvío y 12 flujos en `tables/s1.txt`.

### Pruebas completas en Mininet

```bash
./lab2-counters/scripts/pruebas.sh --completo
```

o directamente:

```bash
sudo python3 lab2-counters/scripts/prueba_automatica.py
```

El script levanta la topología, genera tráfico real, lee los contadores y compara lo esperado con lo medido. La salida se guarda en `resultados_pruebas.txt`.

### Resultados obtenidos

| Prueba | Tráfico generado | Resultado |
|---|---|---|
| 1. Conectividad | `pingAll` entre los 4 hosts | 12/12 exitosas, 0 % de pérdida |
| 2. Contadores por protocolo | h1 → h2: 10 paquetes TCP, UDP, ICMP y otros de 200 B | UDP = 10 y otros = 10. TCP = 20 y ICMP = 26 porque incluyen las respuestas de h2 |
| 3. Contadores por flujo | El mismo tráfico de la prueba 2 | Flujo 10.0.0.1 → 10.0.0.2: 40 paquetes y 8000 bytes. Flujo 10.0.0.1 → 10.0.0.3: 0 |
| 4. Registro de bytes | h3 → h4: 100 paquetes UDP de 1000 B | Contador directo = 100 000 B, register = 100 000 B, contador UDP = 100 000 B, tamaño mínimo y máximo = 1000 B |
| 5. Actualización periódica | Controlador con `--intervalo 5` durante 16 s | 4 lecturas, separadas por 5 s cada una |
| 6. Flujos elefante | h1 → h3: 150 000 B y h2 → h4: 50 000 B, umbral 100 000 B | Solo 10.0.0.1 → 10.0.0.3 queda marcado por el switch y el controlador muestra la alerta |

Total: 22/22 comprobaciones correctas.

En la prueba 4, la categoría 512–1023 B del histograma registró 106 paquetes: los 100 UDP más 6 respuestas ICMP de "puerto inalcanzable" de 590 B que envió h4.

Ejemplo de alerta generada por el controlador:

```text
ALERTA: Flujo elefante detectado

Fecha: 2026-11-23 19:06:29
Origen: 10.0.0.1
Destino: 10.0.0.3
Paquetes: 150
Bytes: 150000
Umbral: 100000
Marcado por el switch: si
```

## Consultas manuales

Con la topología ejecutándose, también se pueden leer los valores directamente:

```bash
echo "counter_read MyIngress.proto_counter 0" | simple_switch_CLI --thrift-port 9090
echo "table_dump MyIngress.flow_stats" | simple_switch_CLI --thrift-port 9090
echo "register_read MyIngress.flow_bytes" | simple_switch_CLI --thrift-port 9090
```

## Finalización

Para salir de Mininet:

```bash
exit
```

Si es necesario limpiar la red:

```bash
sudo mn -c
```
