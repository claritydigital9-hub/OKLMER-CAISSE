# -*- coding: utf-8 -*-
import os
import json
import time
import threading
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from google import genai
from google.genai import types

# 1. CONFIGURATION (à renseigner dans Render > Environment)
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1244852872055806")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "mon_token_secret_oklmzer")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
NUMERO_PATRON = os.environ.get("NUMERO_PATRON") or "22897633742"

GOOGLE_SCRIPT_URL = os.environ.get(
    "GOOGLE_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbztYCqKaMQdWPgZeKidCtZX0aB6uRzWy9gfvr06p8flfRwK2I2MeYYW3iSnnJq8JtJsGw/exec",
)

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
messages_traites = set()


def lire_google_sheet():
    try:
        r = requests.get(GOOGLE_SCRIPT_URL, timeout=15)
        return r.json()
    except Exception as e:
        print(f"Erreur lecture Sheet: {e}", flush=True)
        return {"status": "error"}


def ecrire_google_sheet(payload):
    try:
        r = requests.post(GOOGLE_SCRIPT_URL, json=payload, timeout=15)
        return r.json()
    except Exception as e:
        print(f"Erreur ecriture Sheet: {e}", flush=True)
        return {"status": "error"}


def envoyer_whatsapp_texte(destinataire, texte):
    if not ACCESS_TOKEN:
        print("ACCESS_TOKEN manquant dans Render.", flush=True)
        return
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {"messaging_product": "whatsapp", "to": destinataire, "type": "text", "text": {"body": texte}}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        print(f"Meta -> {destinataire} ({r.status_code}): {r.text}", flush=True)
    except Exception as e:
        print(f"Erreur Meta: {e}", flush=True)


def formater_bilan_patron(donnees):
    res = donnees.get("resume", {})
    stocks = donnees.get("stock", [])
    lignes_stock = []
    for s in stocks:
        if s.get("seuil", 0) > 0:
            alerte = " ⚠️ BAS" if s.get("restant", 0) <= s.get("seuil", 0) else ""
            lignes_stock.append(f"• {s['produit']} : {s['restant']} restants{alerte}")

    bloc_stock = "\n".join(lignes_stock) if lignes_stock else "• Aucun produit physique configuré"
    return (
        f"📊 BILAN CAISSE — OKLMZER GAME (Gbadago)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 Aujourd'hui : {res.get('total_jour', 0):,} FCFA ({res.get('nb_ventes_jour', 0)} ventes)\n"
        f"📅 7 derniers jours : {res.get('total_semaine', 0):,} FCFA\n"
        f"🗓️ Mois en cours : {res.get('total_mois', 0):,} FCFA\n\n"
        f"📦 ÉTAT DES STOCKS :\n{bloc_stock}"
    ).replace(",", " ")


def repondre_patron_ia(expediteur, question):
    donnees = lire_google_sheet()
    if not client_gemini:
        envoyer_whatsapp_texte(expediteur, formater_bilan_patron(donnees))
        return

    prompt = f"""Tu es l'assistante de gestion personnelle du propriétaire d'OKLMZER GAME (salle de jeux et boissons à Gbadago, Lomé).
Réponds de façon claire, directe, chaleureuse et chiffrée en FCFA à sa question, en utilisant UNIQUEMENT les données réelles ci-dessous issues du Google Sheet :

DONNÉES EN DIRECT :
{json.dumps(donnees, ensure_ascii=False)}

RÈGLES :
- Ne invente jamais de chiffre.
- Si un stock est inférieur ou égal à son seuil d'alerte, signale-le clairement avec ⚠️.
- Utilise des emojis propres (📊, 💰, 📦, ⚠️, 🎮) pour que ce soit lisible sur téléphone."""

    for modele in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash-lite", "gemini-2.0-flash"]:
        try:
            resp = client_gemini.models.generate_content(
                model=modele,
                contents=[types.Content(role="user", parts=[types.Part(text=question)])],
                config=types.GenerateContentConfig(system_instruction=prompt, temperature=0.3, max_output_tokens=800),
            )
            if resp.text:
                envoyer_whatsapp_texte(expediteur, resp.text.strip())
                return
        except Exception as e:
            print(f"Erreur Gemini ({modele}): {e}", flush=True)

    envoyer_whatsapp_texte(expediteur, formater_bilan_patron(donnees))


HTML_CAISSE = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Mini-Caisse — OKLMZER GAME</title>
  <style>
    * { box-sizing: border-box; font-family: Arial, sans-serif; }
    body { margin: 0; background: #0F172A; color: #F8FAFC; padding: 14px; }
    .header {
      background: #1E293B; padding: 14px 18px; border-radius: 12px; margin-bottom: 16px;
      display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px;
      border-bottom: 3px solid #EA580C;
    }
    .title { font-size: 20px; font-weight: bold; }
    .sub { font-size: 12px; color: #94A3B8; }
    .total-box { background: #EA580C; padding: 10px 16px; border-radius: 10px; font-weight: bold; font-size: 17px; }
    h2 { font-size: 14px; color: #FB923C; text-transform: uppercase; letter-spacing: 1px; margin: 16px 0 10px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(155px, 1fr)); gap: 10px; }
    .card {
      background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 12px;
      display: flex; flex-direction: column; gap: 8px;
    }
    .card-title { font-weight: bold; font-size: 15px; display: flex; justify-content: space-between; align-items: center; }
    .timer { font-family: monospace; font-size: 16px; color: #FBBF24; font-weight: bold; }
    .timer.done { color: #EF4444; animation: blink 0.8s infinite; }
    @keyframes blink { 50% { opacity: 0.3; } }
    button {
      border: none; border-radius: 9px; padding: 12px 10px; font-size: 14px; font-weight: bold;
      cursor: pointer; color: #FFF; transition: transform 0.1s;
    }
    button:active { transform: scale(0.96); }
    .btn-orange { background: #EA580C; }
    .btn-blue { background: #2563EB; }
    .btn-teal { background: #0D9488; }
    .btn-dark { background: #334155; }
    .btn-green { background: #16A34A; width: 100%; padding: 15px; font-size: 16px; margin-top: 16px; }
    .btn-row { display: flex; gap: 8px; }
    .btn-row button { flex: 1; }
    .stock-badge { font-size: 12px; color: #CBD5E1; }
    .stock-low { color: #FCA5A5; font-weight: bold; }
    #toast {
      position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
      background: #22C55E; color: #052E16; font-weight: bold; padding: 10px 18px;
      border-radius: 30px; display: none; z-index: 999; box-shadow: 0 6px 18px rgba(0,0,0,0.4);
    }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="title">🎮 OKLMZER GAME — Gbadago</div>
      <div class="sub">Mini-Caisse Tactile • Connectée en direct</div>
    </div>
    <div class="total-box">Jour : <span id="total-jour">0</span> FCFA</div>
  </div>

  <h2>🕹️ Consoles & Jeux</h2>
  <div class="grid">
    <div class="card">
      <div class="card-title">PS2 Poste 1</div>
      <button class="btn-orange" onclick="vendre('PS2_MATCH','PlayStation 2','PS2 Poste 1 (Match)',50)">+1 Match • 50 F</button>
    </div>
    <div class="card">
      <div class="card-title">PS2 Poste 2</div>
      <button class="btn-orange" onclick="vendre('PS2_MATCH','PlayStation 2','PS2 Poste 2 (Match)',50)">+1 Match • 50 F</button>
    </div>
    <div class="card">
      <div class="card-title">PS3 Poste 1 <span id="t-ps3-1" class="timer">00:00</span></div>
      <div class="btn-row">
        <button class="btn-blue" onclick="lancerJeu('PS3_30M','PlayStation 3','PS3 Poste 1 (30m)',300,'t-ps3-1',30)">30m • 300 F</button>
        <button class="btn-blue" onclick="lancerJeu('PS3_1H','PlayStation 3','PS3 Poste 1 (1h)',500,'t-ps3-1',60)">1h • 500 F</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">PS3 Poste 2 <span id="t-ps3-2" class="timer">00:00</span></div>
      <div class="btn-row">
        <button class="btn-blue" onclick="lancerJeu('PS3_30M','PlayStation 3','PS3 Poste 2 (30m)',300,'t-ps3-2',30)">30m • 300 F</button>
        <button class="btn-blue" onclick="lancerJeu('PS3_1H','PlayStation 3','PS3 Poste 2 (1h)',500,'t-ps3-2',60)">1h • 500 F</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Jeux Volant <span id="t-volant" class="timer">00:00</span></div>
      <div class="btn-row">
        <button class="btn-teal" onclick="lancerJeu('VOLANT_30M','Jeux Volant','Volant (30m)',500,'t-volant',30)">30m • 500 F</button>
        <button class="btn-teal" onclick="lancerJeu('VOLANT_1H','Jeux Volant','Volant (1h)',1000,'t-volant',60)">1h • 1000 F</button>
      </div>
    </div>
    <div class="card">
      <div class="card-title">Baby-foot</div>
      <button class="btn-dark" onclick="vendre('BABYFOOT','Baby-foot','Baby-foot (1 partie)',25)">+1 Partie • 25 F</button>
    </div>
  </div>

  <h2>💧 Eau, Jus & Yaourt</h2>
  <div class="grid">
    <div class="card">
      <div class="card-title">Pure Water (Gros)</div>
      <div class="stock-badge" id="st-PURE_WATER_GROS">Stock : --</div>
      <button class="btn-orange" onclick="vendre('PURE_WATER_GROS','Boissons','Pure Water Sachet Gros',250)">1 Sachet • 250 F</button>
    </div>
    <div class="card">
      <div class="card-title">Pure Water (Glacé)</div>
      <div class="stock-badge" id="st-PURE_WATER_GLACE">Stock : --</div>
      <button class="btn-orange" onclick="vendre('PURE_WATER_GLACE','Boissons','Pure Water Glacé',25)">1 Unité • 25 F</button>
    </div>
    <div class="card">
      <div class="card-title">Jus / Yaourt (25 F)</div>
      <div class="stock-badge" id="st-JUS_25">Stock : --</div>
      <button class="btn-teal" onclick="vendre('JUS_25','Boissons','Jus / Yaourt 25F',25)">1 Unité • 25 F</button>
    </div>
    <div class="card">
      <div class="card-title">Jus / Yaourt (50 F)</div>
      <div class="stock-badge" id="st-JUS_50">Stock : --</div>
      <button class="btn-teal" onclick="vendre('JUS_50','Boissons','Jus / Yaourt 50F',50)">1 Unité • 50 F</button>
    </div>
  </div>

  <button class="btn-green" onclick="cloturer()">📊 Clôturer et envoyer le bilan au Patron (WhatsApp)</button>
  <div id="toast">Enregistré ✅</div>

  <script>
    var timers = {};

    function showToast(txt) {
      var t = document.getElementById("toast");
      t.innerText = txt;
      t.style.display = "block";
      setTimeout(function() { t.style.display = "none"; }, 1800);
    }

    function bipFin() {
      try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ctx.createOscillator();
        osc.type = "sine"; osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.connect(ctx.destination); osc.start(); osc.stop(ctx.currentTime + 0.6);
      } catch(e) {}
    }

    function lancerJeu(code, cat, article, montant, timerId, minutes) {
      vendre(code, cat, article, montant);
      if (timers[timerId]) clearInterval(timers[timerId]);
      var sec = minutes * 60;
      var el = document.getElementById(timerId);
      el.classList.remove("done");
      timers[timerId] = setInterval(function() {
        sec--;
        if (sec <= 0) {
          clearInterval(timers[timerId]);
          el.innerText = "FINI!";
          el.classList.add("done");
          bipFin();
          return;
        }
        var m = Math.floor(sec / 60), s = sec % 60;
        el.innerText = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
      }, 1000);
    }

    async function chargerEtat() {
      try {
        var r = await fetch("/api/etat");
        var d = await r.json();
        if (d.resume) {
          document.getElementById("total-jour").innerText = (d.resume.total_jour || 0).toLocaleString("fr-FR");
        }
        if (d.stock) {
          d.stock.forEach(function(s) {
            var el = document.getElementById("st-" + s.code);
            if (el) {
              el.innerText = "Stock : " + s.restant;
              el.className = "stock-badge" + (s.seuil > 0 && s.restant <= s.seuil ? " stock-low" : "");
            }
          });
        }
      } catch(e) {}
    }

    async function vendre(code, categorie, article, montant) {
      showToast(article + " (+" + montant + " F) ✅");
      try {
        await fetch("/api/vente", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "vente", code: code, categorie: categorie, article: article, quantite: 1, montant: montant })
        });
        chargerEtat();
      } catch(e) {}
    }

    async function cloturer() {
      showToast("Envoi du bilan au patron...");
      await fetch("/api/cloture", { method: "POST" });
      showToast("Bilan envoyé sur WhatsApp ✅");
    }

    chargerEtat();
  </script>
</body>
</html>
"""


class OklmzerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/caisse":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CAISSE.encode("utf-8"))
            return

        if parsed.path == "/api/etat":
            donnees = lire_google_sheet()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(donnees).encode("utf-8"))
            return

        if parsed.path == "/webhook":
            params = parse_qs(parsed.query)
            if params.get("hub.mode", [""])[0] == "subscribe" and params.get("hub.verify_token", [""])[0] == VERIFY_TOKEN:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(params.get("hub.challenge", [""])[0].encode("utf-8"))
                return
            self.send_response(403)
            self.end_headers()
            return

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Serveur OKLMZER GAME actif. Ouvrez /caisse pour la mini-caisse.")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        data = json.loads(body) if body else {}

        if parsed.path == "/api/vente":
            res = ecrire_google_sheet(data)
            if res.get("alerte"):
                al = res["alerte"]
                msg = f"⚠️ ALERTE STOCK BAS — OKLMZER GAME\n• Produit : {al['produit']}\n• Stock restant : {al['restant']} (seuil : {al['seuil']})"
                threading.Thread(target=envoyer_whatsapp_texte, args=(NUMERO_PATRON, msg), daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return

        if parsed.path == "/api/cloture":
            donnees = lire_google_sheet()
            msg = formater_bilan_patron(donnees)
            threading.Thread(target=envoyer_whatsapp_texte, args=(NUMERO_PATRON, msg), daemon=True).start()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
            return

        try:
            for entry in data.get("entry", []):
                for change in entry.get("changes", []):
                    for msg in change.get("value", {}).get("messages", []):
                        msg_id = msg.get("id")
                        if msg_id in messages_traites:
                            continue
                        messages_traites.add(msg_id)
                        expediteur = msg.get("from", "")
                        if msg.get("type") == "text":
                            threading.Thread(
                                target=repondre_patron_ia,
                                args=(expediteur, msg["text"]["body"]),
                                daemon=True,
                            ).start()
        except Exception as e:
            print(f"Erreur webhook: {e}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"Demarrage OKLMZER GAME sur port {port}", flush=True)
    HTTPServer(("0.0.0.0", port), OklmzerHandler).serve_forever()
