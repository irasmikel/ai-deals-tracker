# 🤖 AI Deals Tracker

Un rastreador automático de ofertas, descuentos y créditos gratis de plataformas de Inteligencia Artificial (ChatGPT, Claude, Gemini, Grok, Perplexity, Copilot, Cursor, etc.).

## ✨ Características

- 📡 **Monitoreo de múltiples fuentes**: Chollometro, HotUKDeals, Reddit
- 🧠 **Análisis inteligente con Gemini**: Diferencia entre ofertas reales y consultas/spam
- 📲 **Notificaciones por Telegram**: Recibe las mejores ofertas al instante
- ⏰ **Automatización con GitHub Actions**: Se ejecuta cada 2 horas sin intervención
- 💾 **Historial de enlaces**: Evita duplicados y mantiene un registro de ofertas ya procesadas

## 🚀 Instalación

### Requisitos
- Python 3.11+
- Cuenta de Telegram con Bot Token
- API Key de Google Gemini
- Variables de entorno configuradas

### Pasos

1. **Clonar el repositorio**
```bash
git clone https://github.com/irasmikel/ai-deals-tracker.git
cd ai-deals-tracker
```

2. **Instalar dependencias**
```bash
pip install -r requirements.txt
```

3. **Configurar variables de entorno**
Crea un archivo `.env` en la raíz del proyecto:
```
TELEGRAM_BOT_TOKEN=tu_token_aqui
TELEGRAM_CHAT_ID=tu_chat_id_aqui
GEMINI_API_KEY=tu_api_key_aqui
```

## 📋 Configuración

### Obtener Telegram Bot Token
1. Habla con [@BotFather](https://t.me/botfather) en Telegram
2. Crea un bot nuevo con `/newbot`
3. Copia el token proporcionado

### Obtener Chat ID
1. Envía un mensaje a tu bot
2. Accede a `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Busca tu `chat_id` en la respuesta

### Obtener API Key de Gemini
1. Ve a [Google AI Studio](https://aistudio.google.com/)
2. Crea una nueva API Key
3. Cópiala en tu `.env`

## 🔧 Uso Local

Ejecuta el script directamente:
```bash
python tracker.py
```

## 🤖 Automatización con GitHub Actions

El proyecto está configurado para ejecutarse automáticamente cada 2 horas mediante GitHub Actions.

**Para activar la automatización:**

1. Ve a **Settings** → **Secrets and variables** → **Actions**
2. Añade los siguientes secretos:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `GEMINI_API_KEY`

3. El workflow se ejecutará automáticamente según el cronograma (cada 2 horas)
4. También puedes ejecutarlo manualmente desde la pestaña **Actions**

## 📊 Fuentes Monitoreadas

### Chollometro (España)
- ChatGPT, Claude, Gemini, Grok, Perplexity, Copilot

### HotUKDeals (UK/Global)
- ChatGPT, Gemini, Perplexity

### Reddit
- r/ChatGPT, r/OpenAI, r/ClaudeAI, r/PerplexityAI, r/cursor, r/ArtificialInteligence

## 📁 Estructura del Proyecto

```
ai-deals-tracker/
├── .github/
│   └── workflows/
│       └── tracker.yml          # Workflow de GitHub Actions
├── .gitignore                    # Archivos a ignorar
├── requirements.txt              # Dependencias Python
├── tracker.py                    # Script principal
├── sent_links.txt                # Historial de enlaces (generado)
└── README.md                     # Este archivo
```

## 🔄 Proceso de Análisis

1. **Obtención de feeds**: Se descargan los últimos posts de cada fuente RSS
2. **Deduplicación**: Se compara contra enlaces ya procesados en `sent_links.txt`
3. **Análisis con Gemini**: Se evalúa si es una oferta real o spam/consulta
4. **Notificación**: Si es una oferta válida, se envía a Telegram con formato especial
5. **Registro**: Se guarda el enlace en el historial

## 📝 Formato de Mensajes

Cuando se detecta una oferta válida, se envía a Telegram en este formato:

```
🚨 *CHOLLO IA: [Título breve]*

• *Servicio:* [Plataforma]
• *Beneficio:* [Meses gratis/Descuento/Crédito]
• *Requisitos:* [Condiciones]
• *Instrucciones:* [Cómo canjearlo]

🔗 [Ver publicación original](enlace)
```

## ⚙️ Variables de Entorno

| Variable | Descripción | Requerido |
|----------|-------------|-----------|
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | ✅ Sí |
| `TELEGRAM_CHAT_ID` | ID del chat donde enviar mensajes | ✅ Sí |
| `GEMINI_API_KEY` | Clave API de Google Gemini | ✅ Sí |

## 🛠️ Tecnologías

- **Python 3.11**: Lenguaje principal
- **feedparser**: Lectura de feeds RSS
- **requests**: Peticiones HTTP
- **Google Gemini API**: Análisis inteligente de contenido
- **Telegram Bot API**: Envío de notificaciones
- **GitHub Actions**: Automatización

## 📄 Licencia

Este proyecto está disponible bajo la licencia MIT.

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor, abre un issue o pull request con tus sugerencias.

## 📞 Contacto

- GitHub: [@irasmikel](https://github.com/irasmikel)

---

⭐ Si te resulta útil, ¡no olvides dejar una estrella!
