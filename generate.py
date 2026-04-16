#!/usr/bin/env python3
"""
Génère dashboard.html avec les données météo, RATP et Vélib en temps réel.
Lancé par GitHub Actions, pousse le résultat sur GitHub Pages.
"""

import json
import urllib.request
import urllib.error
import os
from datetime import datetime, timezone, timedelta

PARIS_TZ = timezone(timedelta(hours=2))  # CEST (été)
now = datetime.now(PARIS_TZ)
heure = now.hour
matin = 0 <= heure <= 11


# ── Helpers ──────────────────────────────────────────────────────────────────

def fetch(url, headers=None):
    h = {"User-Agent": "Paris-Dashboard/1.0", "Accept": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def weather_icon(code):
    if code == 0:   return "☀️"
    if code <= 2:   return "🌤️"
    if code == 3:   return "☁️"
    if code <= 48:  return "🌫️"
    if code <= 67:  return "🌧️"
    if code <= 77:  return "❄️"
    if code <= 82:  return "🌦️"
    return "⛈️"


def weather_desc(code):
    m = {
        0: "Ciel dégagé", 1: "Principalement dégagé", 2: "Partiellement nuageux",
        3: "Couvert", 45: "Brouillard", 48: "Brouillard givrant",
        51: "Bruine légère", 53: "Bruine modérée", 55: "Bruine dense",
        61: "Pluie légère", 63: "Pluie modérée", 65: "Forte pluie",
        71: "Neige légère", 73: "Neige modérée", 75: "Forte neige",
        80: "Averses légères", 81: "Averses", 82: "Averses violentes",
        95: "Orage", 99: "Orage violent",
    }
    return m.get(code, "Conditions inconnues")


# ── Météo ─────────────────────────────────────────────────────────────────────

def get_meteo():
    lat  = 48.8924 if matin else 48.8737
    lon  = 2.2872  if matin else 2.3088
    lieu = "Levallois-Perret" if matin else "Paris 8e"
    slot = "0 h – 11 h 59"   if matin else "12 h – 23 h 59"

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,weathercode"
            f"&forecast_days=1&timezone=Europe%2FParis"
        )
        d = fetch(url)
        h_next = (heure + 1) % 24
        return {
            "ok": True,
            "temp": round(d["hourly"]["temperature_2m"][heure]),
            "rain": d["hourly"]["precipitation_probability"][h_next],
            "code": d["hourly"]["weathercode"][heure],
            "lieu": lieu,
            "slot": slot,
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "lieu": lieu, "slot": slot}


# ── RATP ──────────────────────────────────────────────────────────────────────

RATP_LINES = {
    "1": {"ref": "line:IDFM:C01371", "name": "La Défense ↔ Vincennes",       "color": "#FFBE00", "text": "#1a1200"},
    "2": {"ref": "line:IDFM:C01372", "name": "Nation ↔ Porte Dauphine",      "color": "#003CA6", "text": "#ffffff"},
    "3": {"ref": "line:IDFM:C01373", "name": "Pont de Levallois ↔ Gallieni", "color": "#837902", "text": "#ffffff"},
}

def get_ratp():
    api_key = os.environ.get("IDFM_API_KEY", "")
    results = []
    for num, cfg in RATP_LINES.items():
        status, msg = "ok", "Trafic normal"
        if api_key:
            try:
                url = f"https://prim.iledefrance-mobilites.fr/marketplace/disruptions_bulk/disruptions/v2?line_refs={cfg['ref']}"
                d = fetch(url, {"apikey": api_key})
                disrup = d.get("disruptions", [])
                if disrup:
                    sev = (disrup[0].get("severity") or {}).get("name", "").lower()
                    msg = ((disrup[0].get("messages") or [{}])[0].get("text", "Perturbation"))[:45]
                    status = "err" if "bloquant" in sev else "warn"
            except Exception as e:
                print(f"RATP ligne {num}: {e}")
        results.append({"num": num, "status": status, "msg": msg, **cfg})
    return results


# ── Vélib ─────────────────────────────────────────────────────────────────────

# Mots-cles a chercher dans le nom des stations (insensible a la casse)
VELIB_STATIONS = [
    {"keywords": ["voltaire", "anatole"],  "label": "Voltaire - Anatole France"},
    {"keywords": ["montaigne"],            "label": "Francois 1er - Montaigne"},
]

def get_velib():
    try:
        status_url = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_status.json"
        info_url   = "https://velib-metropole-opendata.smovengo.cloud/opendata/Velib_Metropole/station_information.json"

        status_data = fetch(status_url)
        info_data   = fetch(info_url)

        name_map   = {str(s["station_id"]): s["name"] for s in info_data["data"]["stations"]}
        status_map = {str(s["station_id"]): s         for s in status_data["data"]["stations"]}

        results = []
        for cfg in VELIB_STATIONS:
            found_id   = None
            found_name = cfg["label"]
            for sid, name in name_map.items():
                name_lower = name.lower()
                if all(kw in name_lower for kw in cfg["keywords"]):
                    found_id   = sid
                    found_name = name
                    break

            if found_id and found_id in status_map:
                s     = status_map[found_id]
                bikes = s.get("num_bikes_available", 0)
                docks = s.get("num_docks_available", 0)
                cap   = bikes + docks or 1
                results.append({
                    "ok": True, "id": found_id, "name": found_name,
                    "bikes": bikes, "docks": docks, "cap": cap,
                    "pct_bikes": round(bikes / cap * 100),
                    "pct_docks": round(docks / cap * 100),
                })
                print(f"     Velib OK: {found_name} id={found_id} velos={bikes} places={docks}")
            else:
                print(f"     Velib introuvable: {cfg['label']}")
                results.append({"ok": False, "id": "?", "name": cfg["label"]})

        return results

    except Exception as e:
        print(f"     Erreur Velib: {e}")
        return [{"ok": False, "id": "?", "name": cfg["label"], "error": str(e)} for cfg in VELIB_STATIONS]


# ── Génération HTML ───────────────────────────────────────────────────────────

def meteo_html(m):
    if not m["ok"]:
        return f'<div class="error">⚠ Météo indisponible — {m.get("error","")}</div>'

    icon = weather_icon(m["code"])
    desc = weather_desc(m["code"])
    rain = m["rain"]
    bar_class = "bar-rain" if rain >= 40 else "bar-low"

    return f"""
    <div class="meteo-main">
      <div class="meteo-icon">{icon}</div>
      <div>
        <div class="meteo-temp">{m['temp']}<sup>°C</sup></div>
        <div class="meteo-lieu">{m['lieu']}</div>
        <div class="meteo-desc">{desc}</div>
        <div class="meteo-slot">{m['slot']}</div>
      </div>
    </div>
    <div class="rain-block">
      <div class="rain-header">
        <div class="rain-label">Risque pluie dans l'heure</div>
        <div class="rain-pct">{rain}%</div>
      </div>
      <div class="bar-track">
        <div class="bar-fill {bar_class}" style="width:{rain}%"></div>
      </div>
    </div>"""


def ratp_html(lines):
    rows = []
    for l in lines:
        pill_cls = {"ok": "ok", "warn": "warn", "err": "err"}[l["status"]]
        rows.append(f"""
      <div class="ratp-line">
        <div class="badge" style="background:{l['color']};color:{l['text']}">{l['num']}</div>
        <div class="line-info">
          <div class="line-name">{l['name']}</div>
          <span class="pill {pill_cls}">{l['msg']}</span>
        </div>
      </div>""")
    return '<div class="ratp-lines">' + "".join(rows) + "</div>"


def velib_html(stations):
    cards = []
    for s in stations:
        if not s["ok"]:
            cards.append(f"""
      <div class="station">
        <div class="station-id"># {s['id']}</div>
        <div class="station-name">{s['name']}</div>
        <div class="error">Station introuvable</div>
      </div>""")
            continue

        cards.append(f"""
      <div class="station">
        <div class="station-id"># {s['id']}</div>
        <div class="station-name">{s['name']}</div>
        <div class="station-stats">
          <div class="stat">
            <div class="stat-val bikes">{s['bikes']}</div>
            <div class="stat-lbl">Vélos</div>
          </div>
          <div class="stat-sep"></div>
          <div class="stat">
            <div class="stat-val docks">{s['docks']}</div>
            <div class="stat-lbl">Places</div>
          </div>
        </div>
        <div class="velib-bar-wrap">
          <div class="velib-bar-track">
            <div class="velib-bar-bikes" style="width:{s['pct_bikes']}%"></div>
            <div class="velib-bar-docks" style="width:{s['pct_docks']}%"></div>
          </div>
        </div>
      </div>""")

    return '<div class="velib-grid">' + "".join(cards) + "</div>"


def build_html(meteo, ratp, velib):
    ts = now.strftime("%-d %B %Y · %H h %M")
    jours = ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"]
    jour = jours[now.weekday()]

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="3600">
<title>Paris · Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@300;400;500&family=Syne:wght@400;500;600;700&display=swap');
:root {{
  --bg:#0d0d0f; --surface:#141416; --surface2:#1a1a1d;
  --border:rgba(255,255,255,0.07); --border2:rgba(255,255,255,0.12);
  --text:#f0ede6; --muted:#6b6860; --accent:#e8d5a3; --accent2:#7ec8c8;
  --rain:#5b9bd5; --green:#4eba8a; --red:#e05c5c; --orange:#e8923a;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Syne',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:32px 28px}}
.header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:32px;padding-bottom:16px;border-bottom:1px solid var(--border)}}
.header-left{{display:flex;align-items:baseline;gap:14px}}
.title{{font-family:'DM Serif Display',serif;font-size:26px;color:var(--accent)}}
.subtitle{{font-size:11px;color:var(--muted);letter-spacing:.08em}}
.datetime{{text-align:right}}
.time-big{{font-family:'DM Mono',monospace;font-size:22px;color:var(--text);letter-spacing:.05em}}
.date-str{{font-family:'DM Mono',monospace;font-size:10px;color:var(--muted);margin-top:2px;letter-spacing:.06em}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;max-width:900px}}
@media(max-width:640px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px;overflow:hidden}}
.card.full{{grid-column:1/-1}}
.card-label{{font-family:'DM Mono',monospace;font-size:9px;letter-spacing:.2em;color:var(--muted);text-transform:uppercase;margin-bottom:16px;display:flex;align-items:center;gap:8px}}
.card-label::after{{content:'';flex:1;height:1px;background:var(--border)}}
.meteo-main{{display:flex;align-items:center;gap:16px;margin-bottom:14px}}
.meteo-icon{{font-size:52px;line-height:1;flex-shrink:0}}
.meteo-temp{{font-family:'DM Serif Display',serif;font-size:52px;line-height:1}}
.meteo-temp sup{{font-size:20px;vertical-align:super;color:var(--muted);font-family:'Syne',sans-serif;font-weight:400}}
.meteo-lieu{{font-size:13px;font-weight:600;letter-spacing:.03em}}
.meteo-desc{{font-size:11px;color:var(--muted);margin-top:3px}}
.meteo-slot{{font-size:10px;color:var(--muted);font-family:'DM Mono',monospace;margin-top:2px}}
.rain-block{{margin-top:14px;padding-top:14px;border-top:1px solid var(--border)}}
.rain-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.rain-label{{font-size:10px;color:var(--muted);font-family:'DM Mono',monospace;letter-spacing:.05em}}
.rain-pct{{font-family:'DM Serif Display',serif;font-size:18px;color:var(--rain)}}
.bar-track{{height:5px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden}}
.bar-fill{{height:100%;border-radius:3px}}
.bar-rain{{background:linear-gradient(90deg,#3a7bba,var(--accent2))}}
.bar-low{{background:linear-gradient(90deg,var(--green),#7ec8c8)}}
.ratp-lines{{display:flex;flex-direction:column;gap:12px}}
.ratp-line{{display:flex;align-items:center;gap:12px}}
.badge{{width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:'DM Mono',monospace;font-size:13px;font-weight:500;flex-shrink:0}}
.line-info{{flex:1}}
.line-name{{font-size:10px;color:var(--muted);font-family:'DM Mono',monospace;letter-spacing:.04em;margin-bottom:3px}}
.pill{{display:inline-flex;align-items:center;gap:5px;font-size:10px;font-weight:500;padding:2px 9px;border-radius:20px}}
.pill::before{{content:'';width:5px;height:5px;border-radius:50%;flex-shrink:0}}
.ok{{color:var(--green);background:rgba(78,186,138,.12)}}.ok::before{{background:var(--green)}}
.warn{{color:var(--orange);background:rgba(232,146,58,.12)}}.warn::before{{background:var(--orange)}}
.err{{color:var(--red);background:rgba(224,92,92,.12)}}.err::before{{background:var(--red)}}
.velib-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
.station{{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px}}
.station-id{{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:.12em;margin-bottom:2px}}
.station-name{{font-size:12px;font-weight:600;margin-bottom:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.station-stats{{display:flex;align-items:center;gap:16px}}
.stat{{display:flex;flex-direction:column;gap:2px}}
.stat-val{{font-family:'DM Serif Display',serif;font-size:34px;line-height:1}}
.stat-lbl{{font-size:9px;color:var(--muted);font-family:'DM Mono',monospace;letter-spacing:.08em;text-transform:uppercase}}
.bikes{{color:var(--accent)}}.docks{{color:var(--accent2)}}
.stat-sep{{width:1px;height:36px;background:var(--border)}}
.velib-bar-wrap{{margin-top:10px}}
.velib-bar-track{{height:3px;background:rgba(255,255,255,.06);border-radius:2px;display:flex;gap:1px}}
.velib-bar-bikes{{height:100%;background:var(--accent);border-radius:2px}}
.velib-bar-docks{{height:100%;background:var(--accent2);border-radius:2px}}
.error{{color:var(--red);font-size:11px;font-family:'DM Mono',monospace;padding:4px 0}}
.footer{{margin-top:20px;max-width:900px;display:flex;justify-content:space-between;align-items:center}}
.update-info{{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:.06em}}
.next-info{{font-family:'DM Mono',monospace;font-size:9px;color:var(--muted);letter-spacing:.06em;text-align:right}}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="title">Paris · Dashboard</div>
    <div class="subtitle">Levallois · 8e · RATP · Vélib</div>
  </div>
  <div class="datetime">
    <div class="time-big">{now.strftime('%H h %M')}</div>
    <div class="date-str">{jour} {ts.split('·')[0].strip()}</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <div class="card-label">Météo</div>
    {meteo_html(meteo)}
  </div>
  <div class="card">
    <div class="card-label">RATP · Lignes 1 · 2 · 3</div>
    {ratp_html(ratp)}
  </div>
  <div class="card full">
    <div class="card-label">Vélib · Stations 8038 &amp; 23010</div>
    {velib_html(velib)}
  </div>
</div>

<div class="footer">
  <div class="update-info">Générée le {jour.lower()} {ts} (heure Paris)</div>
  <div class="next-info">Prochaine mise à jour automatique dans ~1 h</div>
</div>

</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"[{now.strftime('%H:%M')}] Génération du dashboard…")

    print("  → Météo…")
    meteo = get_meteo()
    print(f"     {meteo}")

    print("  → RATP…")
    ratp = get_ratp()
    print(f"     {ratp}")

    print("  → Vélib…")
    velib = get_velib()
    print(f"     {velib}")

    html = build_html(meteo, ratp, velib)

    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("  ✓ docs/index.html généré")
