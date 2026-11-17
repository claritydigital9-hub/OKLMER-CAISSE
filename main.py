# -*- coding: utf-8 -*-
import os
import json
import threading
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from google import genai
from google.genai import types

# 1. CONFIGURATION (lue depuis Render > Environment)
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "1244852872055806")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "mon_token_secret_oklmzer")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
NUMERO_PATRON = os.environ.get("NUMERO_PATRON") or "22897633742"
PIN_PATRON = os.environ.get("PIN_PATRON", "1234")

GOOGLE_SCRIPT_URL = os.environ.get(
    "GOOGLE_SCRIPT_URL",
    "https://script.google.com/macros/s/AKfycbztYCqKaMQdWPgZeKidCtZX0aB6uRzWy9gfvr06p8flfRwK2I2MeYYW3iSnnJq8JtJsGw/exec",
)

client_gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
messages_traites = set()

# Suivi live du jour côté serveur (sécurisé même si la date Sheet décale)
caisse_live = {
    "date": datetime.now().strftime("%Y-%m-%d"),
    "total_jour": 0,
    "nb_ventes": 0,
}


def verifier_reset_jour():
    aujourd_hui = datetime.now().strftime("%Y-%m-%d")
    if caisse_live["date"] != aujourd_hui:
        caisse_live["date"] = aujourd_hui
        caisse_live["total_jour"] = 0
        caisse_live["nb_ventes"] = 0


def lire_google_sheet():
    verifier_reset_jour()
    try:
        r = requests.get(GOOGLE_SCRIPT_URL, timeout=15)
        data = r.json()
    except Exception as e:
        print(f"Erreur lecture Sheet: {e}", flush=True)
        data = {"status": "error", "resume": {}, "stock": []}

    res = data.setdefault("resume", {})
    res["total_jour"] = max(int(res.get("total_jour", 0) or 0), caisse_live["total_jour"])
    res["nb_ventes_jour"] = max(int(res.get("nb_ventes_jour", 0) or 0), caisse_live["nb_ventes"])
    res["total_semaine"] = max(int(res.get("total_semaine", 0) or 0), caisse_live["total_jour"])
    res["total_mois"] = max(int(res.get("total_mois", 0) or 0), caisse_live["total_jour"])
    return data


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
        f"💰 Aujourd'hui : {res.get('total_jour', 0):,} FCFA ({res.get('nb_ventes_jour', 0)} articles vendus)\n"
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
Réponds de façon claire, directe, chaleureuse et chiffrée en FCFA à sa question, en utilisant UNIQUEMENT les données réelles ci-dessous :

DONNÉES EN DIRECT :
{json.dumps(donnees, ensure_ascii=False)}

RÈGLES :
- N'invente jamais de chiffre.
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
    .btn-patron {
      background: #334155; color: #E2E8F0; border: 1px solid #475569;
      padding: 10px 14px; border-radius: 10px; font-size: 13px; font-weight: bold; cursor: pointer;
    }
    .layout { display: grid; grid-template-columns: 1fr 310px; gap: 16px; align-items: start; }
    @media (max-width: 820px) { .layout { grid-template-columns: 1fr; } }
    h2 { font-size: 13px; color: #FB923C; text-transform: uppercase; letter-spacing: 1px; margin: 14px 0 8px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; }
    .card {
      background: #1E293B; border: 1px solid #334155; border-radius: 12px; padding: 12px;
      display: flex; flex-direction: column; gap: 8px;
    }
    .card-title { font-weight: bold; font-size: 14px; display: flex; justify-content: space-between; align-items: center; }
    .timer { font-family: monospace; font-size: 15px; color: #FBBF24; font-weight: bold; }
    .timer.done { color: #EF4444; animation: blink 0.8s infinite; }
    @keyframes blink { 50% { opacity: 0.3; } }
    button {
      border: none; border-radius: 9px; padding: 11px 10px; font-size: 13.5px; font-weight: bold;
      cursor: pointer; color: #FFF; transition: transform 0.1s;
    }
    button:active { transform: scale(0.96); }
    .btn-orange { background: #EA580C; }
    .btn-blue { background: #2563EB; }
    .btn-teal { background: #0D9488; }
    .btn-dark { background: #475569; }
    .btn-row { display: flex; gap: 6px; }
    .btn-row button { flex: 1; }
    .stock-badge { font-size: 12px; color: #CBD5E1; }
    .stock-low { color: #FCA5A5; font-weight: bold; }

    /* Ticket Client */
    .ticket-box {
      background: #1E293B; border: 2px solid #EA580C; border-radius: 14px; padding: 14px;
      position: sticky; top: 14px;
    }
    .ticket-head { font-size: 16px; font-weight: bold; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; }
    .ticket-items { max-height: 260px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }
    .ticket-empty { color: #94A3B8; font-size: 13px; text-align: center; padding: 18px 0; }
    .t-row {
      background: #0F172A; padding: 8px 10px; border-radius: 8px;
      display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 13px;
    }
    .t-ctrl { display: flex; align-items: center; gap: 6px; }
    .t-mini { padding: 4px 8px; font-size: 12px; border-radius: 6px; background: #334155; }
    .ticket-total {
      border-top: 1px solid #334155; padding-top: 10px; margin-bottom: 10px;
      display: flex; justify-content: space-between; font-size: 18px; font-weight: bold; color: #FBBF24;
    }
    .btn-valider { background: #16A34A; width: 100%; padding: 14px; font-size: 15px; }
    .btn-vider { background: #DC2626; padding: 5px 10px; font-size: 12px; }

    /* Fenêtre Patron cachée */
    .modal-bg {
      display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.75);
      z-index: 1000; justify-content: center; align-items: center; padding: 16px;
    }
    .modal {
      background: #1E293B; border: 1px solid #475569; border-radius: 14px; padding: 20px;
      width: 100%; max-width: 420px; display: flex; flex-direction: column; gap: 12px;
    }
    .kpi-card { background: #0F172A; padding: 12px; border-radius: 10px; display: flex; justify-content: space-between; font-weight: bold; }
    .kpi-val { color: #22C55E; font-size: 18px; }
    select, input {
      width: 100%; padding: 10px; border-radius: 8px; border: 1px solid #475569;
      background: #0F172A; color: #FFF; font-size: 14px;
    }
    #toast {
      position: fixed; bottom: 18px; left: 50%; transform: translateX(-50%);
      background: #22C55E; color: #052E16; font-weight: bold; padding: 10px 18px;
      border-radius: 30px; display: none; z-index: 2000; box-shadow: 0 6px 18px rgba(0,0,0,0.4);
    }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <div class="title">🎮 OKLMZER GAME — Gbadago</div>
      <div class="sub">Caisse Client Tactile</div>
    </div>
    <button class="btn-patron" onclick="ouvrirMenuPatron()">🔒 Espace Patron</button>
  </div>

  <div class="layout">
    <div>
      <h2>🕹️ Consoles & Jeux</h2>
      <div class="grid">
        <div class="card">
          <div class="card-title">PS2 Poste 1</div>
          <button class="btn-orange" onclick="ajouterPanier('PS2_MATCH','PlayStation 2','PS2 Poste 1 (Match)',50)">+1 Match • 50 F</button>
        </div>
        <div class="card">
          <div class="card-title">PS2 Poste 2</div>
          <button class="btn-orange" onclick="ajouterPanier('PS2_MATCH','PlayStation 2','PS2 Poste 2 (Match)',50)">+1 Match • 50 F</button>
        </div>
        <div class="card">
          <div class="card-title">PS3 Poste 1 <span id="t-ps3-1" class="timer">00:00</span></div>
          <div class="btn-row">
            <button class="btn-blue" onclick="ajouterJeu('PS3_30M','PlayStation 3','PS3 Poste 1 (30m)',300,'t-ps3-1',30)">30m • 300 F</button>
            <button class="btn-blue" onclick="ajouterJeu('PS3_1H','PlayStation 3','PS3 Poste 1 (1h)',500,'t-ps3-1',60)">1h • 500 F</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">PS3 Poste 2 <span id="t-ps3-2" class="timer">00:00</span></div>
          <div class="btn-row">
            <button class="btn-blue" onclick="ajouterJeu('PS3_30M','PlayStation 3','PS3 Poste 2 (30m)',300,'t-ps3-2',30)">30m • 300 F</button>
            <button class="btn-blue" onclick="ajouterJeu('PS3_1H','PlayStation 3','PS3 Poste 2 (1h)',500,'t-ps3-2',60)">1h • 500 F</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">Jeux Volant <span id="t-volant" class="timer">00:00</span></div>
          <div class="btn-row">
            <button class="btn-teal" onclick="ajouterJeu('VOLANT_30M','Jeux Volant','Volant (30m)',500,'t-volant',30)">30m • 500 F</button>
            <button class="btn-teal" onclick="ajouterJeu('VOLANT_1H','Jeux Volant','Volant (1h)',1000,'t-volant',60)">1h • 1000 F</button>
          </div>
        </div>
        <div class="card">
          <div class="card-title">Baby-foot</div>
          <button class="btn-dark" onclick="ajouterPanier('BABYFOOT','Baby-foot','Baby-foot (1 partie)',25)">+1 Partie • 25 F</button>
        </div>
      </div>

      <h2>💧 Eau, Jus & Yaourt</h2>
      <div class="grid">
        <div class="card">
          <div class="card-title">Pure Water (Gros)</div>
          <div class="stock-badge" id="st-PURE_WATER_GROS">Stock : --</div>
          <button class="btn-orange" onclick="ajouterPanier('PURE_WATER_GROS','Boissons','Pure Water Sachet Gros',250)">1 Sachet • 250 F</button>
        </div>
        <div class="card">
          <div class="card-title">Pure Water (Glacé)</div>
          <div class="stock-badge" id="st-PURE_WATER_GLACE">Stock : --</div>
          <button class="btn-orange" onclick="ajouterPanier('PURE_WATER_GLACE','Boissons','Pure Water Glacé',25)">1 Unité • 25 F</button>
        </div>
        <div class="card">
          <div class="card-title">Jus / Yaourt (25 F)</div>
          <div class="stock-badge" id="st-JUS_25">Stock : --</div>
          <button class="btn-teal" onclick="ajouterPanier('JUS_25','Boissons','Jus / Yaourt 25F',25)">1 Unité • 25 F</button>
        </div>
        <div class="card">
          <div class="card-title">Jus / Yaourt (50 F)</div>
          <div class="stock-badge" id="st-JUS_50">Stock : --</div>
          <button class="btn-teal" onclick="ajouterPanier('JUS_50','Boissons','Jus / Yaourt 50F',50)">1 Unité • 50 F</button>
        </div>
      </div>
    </div>

    <div class="ticket-box">
      <div class="ticket-head">
        <span>🧾 Ticket Client</span>
        <button class="btn-vider" onclick="viderPanier()">Vider</button>
      </div>
      <div class="ticket-items" id="ticket-items">
        <div class="ticket-empty">Appuyez sur les articles du client...</div>
      </div>
      <div class="ticket-total">
        <span>TOTAL À PAYER</span>
        <span><span id="ticket-total">0</span> F</span>
      </div>
      <button class="btn-valider" onclick="validerPanier()">✅ Valider & Encaisser</button>
    </div>
  </div>

  <!-- Menu caché Patron / Gérant -->
  <div class="modal-bg" id="modal-patron">
    <div class="modal">
      <div class="card-title" style="font-size:17px;">
        <span>🔒 Espace Patron & Gérant</span>
        <button class="t-mini" onclick="fermerMenuPatron()">✕</button>
      </div>
      <div class="kpi-card">
        <span>Recette du jour :</span>
        <span class="kpi-val"><span id="patron-total-jour">0</span> FCFA</span>
      </div>
      <div class="kpi-card">
        <span>Articles / Jeux vendus :</span>
        <span id="patron-nb-ventes">0</span>
      </div>

      <hr style="border-color:#334155; width:100%; margin:4px 0;">
      <div style="font-size:13px; font-weight:bold; color:#FB923C;">📦 Ajouter du stock (Réapprovisionnement)</div>
      <select id="reappro-code">
        <option value="PURE_WATER_GROS">Pure Water (Sachet Gros)</option>
        <option value="PURE_WATER_GLACE">Pure Water Glacé (Unité)</option>
        <option value="JUS_25">Jus / Yaourt (25 F)</option>
        <option value="JUS_50">Jus / Yaourt (50 F)</option>
      </select>
      <div class="btn-row">
        <input id="reappro-qte" type="number" value="20" min="1" />
        <button class="btn-teal" onclick="ajouterStock()">+ Ajouter</button>
      </div>

      <button class="btn-valider" style="margin-top:6px;" onclick="cloturer()">📊 Clôturer & Envoyer Bilan WhatsApp</button>
    </div>
  </div>

  <div id="toast">Enregistré ✅</div>

  <script>
    var panier = [];
    var timers = {};
    var timersAttente = [];

    function showToast(txt) {
      var t = document.getElementById("toast");
      t.innerText = txt;
      t.style.display = "block";
      setTimeout(function() { t.style.display = "none"; }, 2000);
    }

    function bipFin() {
      try {
        var ctx = new (window.AudioContext || window.webkitAudioContext)();
        var osc = ctx.createOscillator();
        osc.type = "sine"; osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.connect(ctx.destination); osc.start(); osc.stop(ctx.currentTime + 0.6);
      } catch(e) {}
    }

    function demarrerTimer(timerId, minutes) {
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

    function ajouterJeu(code, cat, article, prix, timerId, minutes) {
      ajouterPanier(code, cat, article, prix);
      timersAttente.push({ timerId: timerId, minutes: minutes });
    }

    function ajouterPanier(code, categorie, article, prix) {
      var existant = panier.find(function(x) { return x.article === article; });
      if (existant) {
        existant.quantite += 1;
      } else {
        panier.push({ code: code, categorie: categorie, article: article, prix: prix, quantite: 1 });
      }
      afficherPanier();
    }

    function changerQte(index, delta) {
      panier[index].quantite += delta;
      if (panier[index].quantite <= 0) panier.splice(index, 1);
      afficherPanier();
    }

    function viderPanier() {
      panier = [];
      timersAttente = [];
      afficherPanier();
    }

    function afficherPanier() {
      var box = document.getElementById("ticket-items");
      var totalEl = document.getElementById("ticket-total");
      if (panier.length === 0) {
        box.innerHTML = '<div class="ticket-empty">Appuyez sur les articles du client...</div>';
        totalEl.innerText = "0";
        return;
      }
      var total = 0;
      var html = "";
      panier.forEach(function(item, i) {
        var sousTotal = item.prix * item.quantite;
        total += sousTotal;
        html += '<div class="t-row">' +
          '<div><strong>' + item.quantite + 'x</strong> ' + item.article + '<br><span style="color:#FBBF24;">' + sousTotal + ' F</span></div>' +
          '<div class="t-ctrl">' +
            '<button class="t-mini" onclick="changerQte(' + i + ',-1)">-</button>' +
            '<button class="t-mini" onclick="changerQte(' + i + ',1)">+</button>' +
          '</div>' +
        '</div>';
      });
      box.innerHTML = html;
      totalEl.innerText = total.toLocaleString("fr-FR");
    }

    async function validerPanier() {
      if (panier.length === 0) return showToast("Le ticket est vide");
      var total = panier.reduce(function(acc, x) { return acc + x.prix * x.quantite; }, 0);
      var articlesAEnvoyer = panier.slice();
      var timersALancer = timersAttente.slice();
      viderPanier();

      timersALancer.forEach(function(t) { demarrerTimer(t.timerId, t.minutes); });
      showToast("Encaissé : " + total + " FCFA ✅");

      try {
        await fetch("/api/panier", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: articlesAEnvoyer })
        });
        chargerEtat();
      } catch(e) {}
    }

    async function chargerEtat() {
      try {
        var r = await fetch("/api/etat");
        var d = await r.json();
        if (d.resume) {
          document.getElementById("patron-total-jour").innerText = (d.resume.total_jour || 0).toLocaleString("fr-FR");
          document.getElementById("patron-nb-ventes").innerText = d.resume.nb_ventes_jour || 0;
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

    async function ouvrirMenuPatron() {
      var code = prompt("Entrez le code PIN Patron :");
      if (!code) return;
      var r = await fetch("/api/verifier-pin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pin: code })
      });
      var res = await r.json();
      if (!res.ok) return alert("Code PIN incorrect ❌");
      await chargerEtat();
      document.getElementById("modal-patron").style.display = "flex";
    }

    function fermerMenuPatron() {
      document.getElementById("modal-patron").style.display = "none";
    }

    async function ajouterStock() {
      var code = document.getElementById("reappro-code").value;
      var qte = parseInt(document.getElementById("reappro-qte").value || "0", 10);
      if (qte <= 0) return;
      await fetch("/api/vente", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "reappro", code: code, quantite: qte })
      });
      showToast("Stock mis à jour (+" + qte + ") ✅");
      chargerEtat();
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
        self.wfile.write(b"Serveur OKLMZER GAME actif.")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        data = json.loads(body) if body else {}

        if parsed.path == "/api/verifier-pin":
            ok = str(data.get("pin", "")).strip() == str(PIN_PATRON)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": ok}).encode("utf-8"))
            return

        if parsed.path == "/api/panier":
            verifier_reset_jour()
            items = data.get("items", [])
            for item in items:
                qte = int(item.get("quantite", 1))
                prix = int(item.get("prix", 0))
                montant = qte * prix
                caisse_live["total_jour"] += montant
                caisse_live["nb_ventes"] += qte

                payload = {
                    "action": "vente",
                    "code": item.get("code", ""),
                    "categorie": item.get("categorie", ""),
                    "article": item.get("article", ""),
                    "quantite": qte,
                    "montant": montant,
                }
                res = ecrire_google_sheet(payload)
                if res.get("alerte"):
                    al = res["alerte"]
                    msg = f"⚠️ ALERTE STOCK BAS — OKLMZER GAME\n• Produit : {al['produit']}\n• Stock restant : {al['restant']} (seuil : {al['seuil']})"
                    threading.Thread(target=envoyer_whatsapp_texte, args=(NUMERO_PATRON, msg), daemon=True).start()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "total_jour": caisse_live["total_jour"]}).encode("utf-8"))
            return

        if parsed.path == "/api/vente":
            res = ecrire_google_sheet(data)
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
