# Asistente RB

Espacio de trabajo con modelos de lenguaje propios, para el equipo de Russell
Bedford. Cada persona conversa, arma **agentes** con instrucciones y documentos
propios, y consulta sobre la información que ella misma cargó.

Es un proyecto **independiente** de `analitica-puc`: base de datos aparte,
usuarios aparte, despliegue aparte. Comparte el linaje técnico —FastAPI,
psycopg, React, Tailwind— y el lenguaje visual de la marca, con acento propio
para que nadie confunda una herramienta con la otra.

## La idea en una frase

El modelo no sabe nada del negocio: sabe redactar y razonar. Lo que lo hace
útil es **el contexto que se le pone delante**, y ese contexto sale de los
documentos que el usuario cargó, recuperados por parecido con su pregunta.
Todo lo que el asistente afirma sobre esos documentos viene con la cita del
fragmento de donde salió.

## Qué corre por debajo

- **Ollama** en el servidor de oficina, sobre CPU. Un modelo de conversación
  (3B–4B, para que responda a ritmo utilizable) y uno de *embeddings*.
- **Postgres** para usuarios, documentos, fragmentos, agentes y conversaciones.
- **FastAPI** como puerta única: sesión obligatoria y bitácora de todo.
- **React + Vite** para la interfaz.

## Realidad del hardware, dicha de frente

En CPU sin GPU un modelo de 8B responde a unos 5–10 tokens por segundo y
atiende **una conversación a la vez**. Por eso:

- El modelo de conversación por defecto es pequeño (3B–4B).
- Las respuestas van *en streaming*: se ven mientras se generan, en vez de
  dejar la pantalla en blanco medio minuto.
- Hay una cola visible. Si otro usuario está generando, se dice, en vez de
  fingir que no pasa nada.

## Instalación

```bash
sudo -u postgres createdb asistente_rb
psql "$ASISTENTE_DSN" -v ON_ERROR_STOP=1 -f schema.sql

python -m venv .venv && .venv/bin/pip install -r requirements.txt

ollama pull qwen2.5:3b-instruct      # conversación
ollama pull bge-m3                   # embeddings, multilingüe (español)

.venv/bin/python usuarios.py crear   # el primer administrador
```

Variables de entorno:

| Variable | Para qué | Por defecto |
|---|---|---|
| `ASISTENTE_DSN` | Conexión a Postgres | `postgresql:///asistente_rb` |
| `OLLAMA_URL` | Dónde escucha Ollama | `http://127.0.0.1:11434` |
| `MODELO_CHAT` | Modelo de conversación | `qwen2.5:3b-instruct` |
| `MODELO_EMBED` | Modelo de embeddings | `bge-m3` |
| `SESION_SEGURA` | Cookie solo por HTTPS | `0` |
| `ARCHIVOS` | Dónde se guardan los documentos | `./archivos` |

`SESION_SEGURA=1` en cuanto haya HTTPS: en `0` la cookie de sesión viaja sin
cifrar.

## Recuperación: cómo encuentra el fragmento correcto

Dos caminos, y el sistema **dice cuál usó**:

1. **Por significado.** Se compara el *embedding* de la pregunta contra el de
   cada fragmento del alcance (los documentos del agente, o los del usuario).
   Es exacto, no aproximado: se calculan todas las distancias.
2. **Por palabras.** Índice de texto completo en español. Encuentra lo que el
   parecido semántico pierde: un NIT, un número de factura, un nombre propio.

Los dos resultados se mezclan. Cuando el alcance supera el tope de fragmentos
que se pueden comparar de una vez, **se declara** en la respuesta en vez de
recortar en silencio.

No hay base de datos vectorial y es una decisión, no una omisión: un agente
apunta a decenas de documentos, no a millones, y para ese tamaño la búsqueda
exacta es más simple, más rápida de operar y no puede equivocarse. El día que
un agente pase de unos veinte mil fragmentos, el camino es `pgvector`.

## Aislamiento

Cada documento y cada agente tienen dueño. **Nadie ve lo del otro** salvo que
su dueño lo comparta explícitamente. Es lo correcto cuando lo que se sube son
papeles de clientes: compartir tiene que ser un acto deliberado, nunca el
comportamiento por defecto.

## Estructura

| Archivo | Responsabilidad |
|---|---|
| `schema.sql` | Tablas, llaves e índices. Toda la lógica vive en Python. |
| `db.py` | Pool de conexiones y consultas. |
| `auth.py` | Contraseñas (scrypt) y tokens de sesión. |
| `ia.py` | Cliente de Ollama: conversación, streaming, embeddings. |
| `documentos.py` | Extracción de texto, troceado y vectorización. |
| `busqueda.py` | Recuperación de fragmentos y armado del contexto. |
| `agentes.py` | Agentes y el prompt que se les arma. |
| `chat.py` | Orquestación de la conversación. |
| `main.py` | API, sesión obligatoria y bitácora. |
| `usuarios.py` | Alta del primer administrador, desde el servidor. |
