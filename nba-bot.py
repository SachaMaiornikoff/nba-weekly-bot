import sqlite3
from datetime import datetime, timedelta
import pytz
import logging
import json
import os
import discord
from openai import OpenAI

# ------------------------
# CONFIG
# ------------------------
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
DISCORD_CHANNEL_ID = int(os.environ["DISCORD_CHANNEL_ID"])
DB_FILE = "games.db"

client_openai = OpenAI(api_key=OPENAI_API_KEY)

# logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ------------------------
# Fonction de conversion ET -> Paris
# ------------------------
def convert_et_to_paris(date_str, time_str):
    et = pytz.timezone("US/Eastern")
    paris = pytz.timezone("Europe/Paris")
    dt = datetime.strptime(date_str + " " + time_str, "%Y-%m-%d %H:%M")
    dt_et = et.localize(dt)
    dt_paris = dt_et.astimezone(paris)
    return dt_paris.strftime("%Y-%m-%d %H:%M")

# ------------------------
# Création BDD si nécessaire
# ------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE NOT NULL,
        opponent TEXT NOT NULL,
        home BOOLEAN NOT NULL,
        team_rank INTEGER,
        opponent_rank INTEGER,
        time_et TEXT NOT NULL,
        time_paris TEXT NOT NULL,
        watch TEXT NOT NULL,
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    conn.commit()
    conn.close()

# ------------------------
# Récupération programme Cavs via OpenAI
# ------------------------
def fetch_cavs_schedule():
    today = datetime.today().date()
    next_sunday = today + timedelta(days=(6 - today.weekday()))
    end_of_week = next_sunday + timedelta(days=6)

    prompt = f"""
    Donne-moi le programme NBA des Cleveland Cavaliers pour la semaine du {next_sunday} au {end_of_week}.
    Pour chaque match, indique :
    - date (YYYY-MM-DD)
    - équipe adverse
    - domicile ou extérieur
    - classement actuel de Cleveland
    - classement actuel de l'adversaire
    - heure brute en US/Eastern (HH:MM)
    - watch: "full" ou "condensed"
    - un petit résumé rapide des enjeux du match
    Réponds uniquement en JSON dans le format suivant :
    [
      {{
        "date": "YYYY-MM-DD",
        "opponent": "Nom de l'équipe",
        "home": true/false,
        "team_rank": <classement Cleveland>,
        "opponent_rank": <classement adversaire>,
        "time_et": "HH:MM",
        "watch": "full" ou "condensed",
        "summary": "texte court"
      }}
    ]
    """

    response = client_openai.chat.completions.create(
        model="gpt-5-chat-latest",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1
    )

    logging.info("Réponse complète de l'API:\n%s", json.dumps(response.to_dict(), indent=2, ensure_ascii=False))

    json_output = response.choices[0].message.content
    try:
        data = json.loads(json_output)
        return data
    except json.JSONDecodeError:
        print("Erreur JSON :", json_output)
        return []

# ------------------------
# Sauvegarde dans la BDD
# ------------------------
def save_to_db(data):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for match in data:
        date_paris = convert_et_to_paris(match['date'], match['time_et'])
        c.execute('''
            INSERT INTO games (date, opponent, home, team_rank, opponent_rank, time_et, time_paris, watch, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            match['date'],
            match['opponent'],
            match['home'],
            match.get('team_rank'),
            match.get('opponent_rank'),
            match['time_et'],
            date_paris,
            match['watch'],
            match.get('summary')
        ))
    conn.commit()
    conn.close()

# ------------------------
# Envoi sur Discord
# ------------------------
async def send_discord_message():
    client = discord.Client(intents=discord.Intents.default())

    @client.event
    async def on_ready():
        print(f'Logged in as {client.user}')
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT date, opponent, home, time_paris, watch, summary FROM games ORDER BY date")
        rows = c.fetchall()
        conn.close()

        message = "**📅 Programme NBA des Cavaliers (Semaine prochaine) :**\n\n"
        for row in rows:
            date, opponent, home, time_paris, watch, summary = row
            domicile = "🏠" if home else "🏟️"
            message += f"**{date} {time_paris}** {domicile} vs *{opponent}* → **{watch.upper()}**\n_{summary}_\n\n"

        channel = client.get_channel(DISCORD_CHANNEL_ID)
        await channel.send(message)
        await client.close()

    await client.start(DISCORD_TOKEN)

if not os.path.exists(DB_FILE):
    print("📀 Aucune base trouvée, création de games.db...")
    init_db()
else:
    print("✅ Base SQLite déjà existante, on continue.")
# ------------------------
# Main
# ------------------------
if __name__ == "__main__":
    init_db()
    matches = fetch_cavs_schedule()
    save_to_db(matches)

    import asyncio
    asyncio.run(send_discord_message())
