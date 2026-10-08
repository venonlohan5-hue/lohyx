"""
Lohyx Hub - launcher Minecraft nouvelle génération.
Profils (Vanilla / Fabric / Forge), mods + shaders + packs de ressources (Modrinth),
détecteur de puissance du PC (vert / jaune / orange / rouge), Boost FPS, serveurs en direct,
skins, actualités, sauvegardes de mondes, connexion Microsoft optionnelle.
L'interface s'ouvre dans une fenêtre d'application (Edge / Chrome), tout reste sur ton PC.
"""
import os
import re
import sys
import json
import time
import uuid
import shutil
import hashlib
import socket
import struct
import inspect
import secrets
import platform
import threading
import subprocess
import webbrowser
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer

try:
    import minecraft_launcher_lib as mll
except ImportError:
    mll = None
    if not getattr(sys, "frozen", False):
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "minecraft-launcher-lib"])
            import minecraft_launcher_lib as mll
        except Exception:
            mll = None

NOM = "Lohyx Hub"
VERSION = "1.1.0"
# Adresse de TON site de mises à jour (le dossier qui contient version.json), sans « / » à la fin.
# Exemple : "https://tonpseudo.github.io/lohyx"   (voir LISEZMOI.txt)
UPDATE_URL = "https://venonlohan5-hue.github.io/lohyx"
CHEMIN_SCRIPT = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
MAJ = {"dispo": False, "version": "", "notes": [], "fichier": "", "sha256": "", "erreur": ""}
DOSSIER = os.path.join(os.path.expanduser("~"), ".lohyx")
F_REGLAGES = os.path.join(DOSSIER, "reglages.json")
F_PROFILS = os.path.join(DOSSIER, "profils.json")
F_SERVEURS = os.path.join(DOSSIER, "serveurs.json")
F_COMPTE = os.path.join(DOSSIER, "compte.json")
# Colle ici ton Client ID Azure (approuvé par Microsoft) pour que tes amis n'aient rien à saisir.
CLIENT_ID = ""
UA = {"User-Agent": "LohyxHub/1.0 (projet perso)"}
TOKEN = secrets.token_urlsafe(24)
DEFAUT = {"pseudo": "Joueur", "accent": "#1bd96a", "ram": 4}
DOSSIERS_MR = {"mods": ("mod", "mods"), "shaders": ("shader", "shaderpacks"),
               "packs": ("resourcepack", "resourcepacks")}
BOOST = ["sodium", "lithium", "ferrite-core", "entityculling", "modernfix"]

P = {"status": "Prêt", "pct": 0, "max": 1, "busy": False, "running": False, "error": ""}
ETAT = {"beat": 0.0, "beats": 0}
SPECS = {}
COMPTE = None
LOGIN = {"msg": "", "busy": False}
NEWS = {"t": 0, "data": []}
VERROU = threading.Lock()


# ================================================================ outils
def lire_json(chemin, defaut):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defaut


def ecrire_json(chemin, donnees):
    os.makedirs(DOSSIER, exist_ok=True)
    tmp = chemin + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False)
    os.replace(tmp, chemin)


def reglages():
    return {**DEFAUT, **lire_json(F_REGLAGES, {})}


def dossier_instance(nom):
    return os.path.join(DOSSIER, "instances", nom)


def api_modrinth(chemin, **params):
    url = "https://api.modrinth.com/v2" + chemin
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def telecharger(url, destination):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, \
            open(destination, "wb") as f:
        shutil.copyfileobj(r, f)


def appeler(fonction, *args, java=None, **kwargs):
    if java:
        try:
            return fonction(*args, java=java, **kwargs)
        except TypeError:
            pass
    return fonction(*args, **kwargs)


def appeler_filtre(fonction, **kwargs):
    params = inspect.signature(fonction).parameters
    return fonction(**{k: v for k, v in kwargs.items() if k in params})


def version_tuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def separer_adresse(adresse):
    m = re.fullmatch(r"([A-Za-z0-9.\-]+)(?::(\d{1,5}))?", adresse.strip())
    return (m.group(1), int(m.group(2) or 25565)) if m else None


def statut(texte, pct=None):
    P["status"] = texte
    if pct is not None:
        P["pct"] = pct


# ================================================================ ping serveur
def _varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _lire_varint(s):
    n = 0
    for i in range(5):
        b = s.recv(1)
        if not b:
            raise ConnectionError("connexion fermée")
        n |= (b[0] & 0x7F) << (7 * i)
        if not b[0] & 0x80:
            return n
    raise ValueError("réponse invalide")


def _lire_exact(s, n):
    data = b""
    while len(data) < n:
        part = s.recv(n - len(data))
        if not part:
            raise ConnectionError("connexion fermée")
        data += part
    return data


def ping_serveur(hote, port=25565, delai=4):
    debut = time.time()
    with socket.create_connection((hote, port), timeout=delai) as s:
        s.settimeout(delai)
        h = hote.encode("utf-8")
        paquet = _varint(0) + _varint(765) + _varint(len(h)) + h + struct.pack(">H", port) + _varint(1)
        s.sendall(_varint(len(paquet)) + paquet)
        s.sendall(_varint(1) + _varint(0))
        _lire_varint(s)
        if _lire_varint(s) != 0:
            raise ValueError("réponse invalide")
        d = json.loads(_lire_exact(s, _lire_varint(s)).decode("utf-8"))
    d["ms"] = int((time.time() - debut) * 1000)
    return d


def texte_motd(d):
    if isinstance(d, str):
        return d
    if isinstance(d, list):
        return "".join(texte_motd(e) for e in d)
    if isinstance(d, dict):
        return d.get("text", "") + "".join(texte_motd(e) for e in d.get("extra", []))
    return ""


# ================================================================ puissance du PC
def tier_gpu(nom):
    n = nom.lower()
    if re.search(r"basic|virtual|vmware|parallels|remote", n):
        return 0
    if re.search(r"uhd|iris|hd graphics|vega|radeon graphics|radeon\(tm\) graphics|\bmx ?\d|intel", n) \
            and "arc" not in n:
        return 1
    if re.search(r"rtx|rx ?[67]\d{3}|rx ?9\d{3}|arc a[57]|titan", n):
        return 3
    if re.search(r"gtx|radeon|rx|arc|quadro|geforce|nvidia", n):
        return 2
    return 1


def _cmd(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15,
                          creationflags=0x08000000 if os.name == "nt" else 0).stdout


def detecter_specs():
    ram = None
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        m = MS()
        m.dwLength = ctypes.sizeof(m)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        ram = m.ullTotalPhys / 2 ** 30
    except Exception:
        try:
            with open("/proc/meminfo") as f:
                ram = int(f.readline().split()[1]) / 2 ** 20
        except Exception:
            pass
    gpus = []
    try:
        if os.name == "nt":
            sortie = _cmd(["powershell", "-NoProfile", "-Command",
                           "(Get-CimInstance Win32_VideoController).Name"])
            if not sortie.strip():
                sortie = _cmd(["wmic", "path", "win32_VideoController", "get", "name"])
            gpus = [l.strip() for l in sortie.splitlines() if l.strip() and l.strip().lower() != "name"]
    except Exception:
        pass
    cpu = os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor() or "Processeur"
    SPECS.update({"ram": round(ram, 1) if ram else None, "threads": os.cpu_count() or 4,
                  "cpu": cpu.split(",")[0][:60], "gpus": gpus or ["Inconnue"],
                  "gpu_tier": max([tier_gpu(g) for g in gpus] or [1]), "pret": True})


def besoins(version, loader, nb_mods, shaders):
    v = version_tuple(version)
    if v >= (1, 18):
        ram, thr, gpu = 3.0, 4, 1
    elif v >= (1, 13):
        ram, thr, gpu = 2.5, 3, 1
    else:
        ram, thr, gpu = 1.5, 2, 0
    if loader != "Vanilla":
        ram += 0.5
    ram += min(nb_mods, 150) * 0.03
    if nb_mods > 60:
        thr += 1
    if shaders:
        ram += 1.5
        thr += 2
        gpu = 2
    return ram, thr, gpu


LABELS = {"vert": "Parfait", "jaune": "Il faut se calmer", "orange": "Pas assez puissant",
          "rouge": "Quasi impossible"}
MESSAGES = {
    "vert": "Ton PC gère ça sans problème.",
    "jaune": "Ça passe, mais baisse la distance d'affichage et ferme les autres programmes.",
    "orange": "Très limite, ça va ramer. Active le Boost FPS et mets les réglages au minimum.",
    "rouge": "Pratiquement impossible de jouer correctement sur ce PC avec cette configuration.",
}


def verdict(specs, version, loader, nb_mods=0, shaders=False):
    ram_need, thr_need, gpu_need = besoins(version, loader, nb_mods, shaders)
    ram = specs.get("ram") or 8
    thr = specs.get("threads") or 4
    tier = specs.get("gpu_tier", 1)
    gpus = specs.get("gpus") or ["Inconnue"]
    details = [
        {"nom": "Mémoire (RAM)", "info": f"{ram:g} Go", "ratio": min(1, ram / (ram_need + 3.5))},
        {"nom": "Processeur", "info": f"{thr} threads", "ratio": min(1, thr / thr_need)},
        {"nom": "Carte graphique", "info": gpus[0][:32], "ratio": min(1, (tier + 1) / (gpu_need + 1))},
    ]
    pire = min(details, key=lambda d: d["ratio"])
    r = pire["ratio"]
    niveau = "vert" if r >= 0.95 else "jaune" if r >= 0.75 else "orange" if r >= 0.55 else "rouge"
    msg = MESSAGES[niveau] + (f" Point faible : {pire['nom'].lower()}." if niveau != "vert" else "")
    return {"niveau": niveau, "score": int(100 * r), "label": LABELS[niveau], "message": msg,
            "details": [{**d, "ratio": round(d["ratio"], 2)} for d in details]}


# ================================================================ profils
def charger_profils():
    return lire_json(F_PROFILS, [])


def trouver(nom):
    p = next((x for x in charger_profils() if x["nom"] == nom), None)
    if not p:
        raise RuntimeError("Profil introuvable.")
    return p


def lister(p, genre):
    d = os.path.join(dossier_instance(p["nom"]), DOSSIERS_MR[genre][1])
    try:
        return sorted(f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    except OSError:
        return []


def enrichir(p):
    mods = [f for f in lister(p, "mods") if f.endswith(".jar")]
    shaders = bool(lister(p, "shaders"))
    return {**p, "nb_mods": len(mods), "shaders": shaders,
            "verdict": verdict(SPECS, p["version"], p["loader"], len(mods), shaders)}


def api_state(_):
    return {"nom": NOM, "reglages": reglages(), "profils": [enrichir(p) for p in charger_profils()],
            "serveurs": lire_json(F_SERVEURS, []), "specs": SPECS, "mll": mll is not None,
            "compte": {"name": COMPTE["name"]} if COMPTE else None, "login": LOGIN,
            "login_ok": bool(CLIENT_ID or lire_json(F_COMPTE, {}).get("client_id")),
            "version": VERSION, "maj": dict(MAJ), "maj_actif": bool(UPDATE_URL.strip())}


def api_profil_creer(b):
    nom, version, loader = b["nom"].strip(), b["version"], b["loader"]
    if not re.fullmatch(r"[\w \-]{1,30}", nom):
        raise RuntimeError("Nom invalide (lettres, chiffres, espaces, - et _, 30 max).")
    if loader not in ("Vanilla", "Fabric", "Forge"):
        raise RuntimeError("Type inconnu.")
    with VERROU:
        l = charger_profils()
        if any(p["nom"].lower() == nom.lower() for p in l):
            raise RuntimeError("Ce nom existe déjà.")
        l.append({"nom": nom, "version": version, "loader": loader,
                  "ram": max(1, min(64, int(b.get("ram", 4)))), "temps": 0})
        ecrire_json(F_PROFILS, l)
    for sous in ("mods", "shaderpacks", "resourcepacks"):
        os.makedirs(os.path.join(dossier_instance(nom), sous), exist_ok=True)
    return {"ok": True}


def api_profil_supprimer(b):
    with VERROU:
        ecrire_json(F_PROFILS, [p for p in charger_profils() if p["nom"] != b["nom"]])
    shutil.rmtree(dossier_instance(b["nom"]), ignore_errors=True)
    return {"ok": True}


def ouvrir_chemin(chemin):
    os.makedirs(chemin, exist_ok=True)
    if os.name == "nt":
        os.startfile(chemin)
    else:
        subprocess.Popen(["xdg-open", chemin])


def api_profil_ouvrir(b):
    ouvrir_chemin(dossier_instance(trouver(b["nom"])["nom"]))
    return {"ok": True}


def api_sauvegarde(b):
    p = trouver(b["nom"])
    saves = os.path.join(dossier_instance(p["nom"]), "saves")
    if not os.path.isdir(saves) or not os.listdir(saves):
        raise RuntimeError("Aucun monde à sauvegarder dans ce profil.")
    dest = os.path.join(DOSSIER, "sauvegardes")
    os.makedirs(dest, exist_ok=True)
    base = os.path.join(dest, f"{p['nom']}_{time.strftime('%Y-%m-%d_%Hh%M')}")
    shutil.make_archive(base, "zip", saves)
    ouvrir_chemin(dest)
    return {"ok": True, "fichier": base + ".zip"}


def api_versions(_):
    try:
        v = [x["id"] for x in mll.utils.get_version_list() if x["type"] == "release"]
    except Exception:
        v = ["1.21.4", "1.21.1", "1.20.4", "1.20.1", "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9"]
    return {"versions": v}


def api_verdict(a):
    return verdict(SPECS, a["version"], a["loader"], int(a.get("mods", 0)), a.get("shaders") == "1")


def api_perf(_):
    lignes = []
    for v in ["1.8.9", "1.12.2", "1.16.5", "1.20.1", "1.21.1"]:
        lignes.append({"version": v,
                       "vanilla": verdict(SPECS, v, "Vanilla"),
                       "mods": verdict(SPECS, v, "Fabric", 60),
                       "shaders": verdict(SPECS, v, "Fabric", 30, True)})
    return {"specs": SPECS, "lignes": lignes}


# ================================================================ mods / shaders / packs
def api_chercher(a):
    p = trouver(a["nom"])
    genre = a.get("genre", "mods")
    if genre == "mods" and p["loader"] == "Vanilla":
        raise RuntimeError("Ce profil est Vanilla (sans mods). Crée un profil Fabric ou Forge.")
    facettes = [[f"project_type:{DOSSIERS_MR[genre][0]}"], [f"versions:{p['version']}"]]
    if genre == "mods":
        facettes.append([f"categories:{p['loader'].lower()}"])
    q = a.get("q", "").strip()
    d = api_modrinth("/search", query=q, facets=json.dumps(facettes), limit=30,
                     index="relevance" if q else "downloads")
    return {"resultats": [{"id": h["project_id"], "titre": h["title"], "desc": h["description"],
                           "dl": h["downloads"], "icone": h.get("icon_url") or "",
                           "auteur": h.get("author", "")} for h in d["hits"]]}


def installer_projet(pid, p, genre, vus):
    if pid in vus:
        return 0
    vus.add(pid)
    dossier = os.path.join(dossier_instance(p["nom"]), DOSSIERS_MR[genre][1])
    os.makedirs(dossier, exist_ok=True)
    params = {"game_versions": json.dumps([p["version"]])}
    if genre == "mods":
        params["loaders"] = json.dumps([p["loader"].lower()])
    versions = api_modrinth(f"/project/{pid}/version", **params)
    if not versions:
        raise RuntimeError("Aucune version compatible avec ce profil.")
    v = versions[0]
    fichier = next((f for f in v["files"] if f.get("primary")), v["files"][0])
    nom_fichier = os.path.basename(fichier["filename"])
    statut(f"Téléchargement : {nom_fichier}")
    dest = os.path.join(dossier, nom_fichier)
    n = 0
    if not os.path.exists(dest):
        telecharger(fichier["url"], dest)
        n = 1
    if genre == "mods":
        for dep in v.get("dependencies", []):
            if dep.get("dependency_type") == "required" and dep.get("project_id"):
                try:
                    n += installer_projet(dep["project_id"], p, genre, vus)
                except Exception:
                    pass
    return n


def api_installer(b):
    P["busy"] = True
    try:
        n = installer_projet(b["id"], trouver(b["nom"]), b.get("genre", "mods"), set())
        statut("Installé !", 100)
        return {"ok": True, "n": n}
    finally:
        P["busy"] = False


def api_boost(b):
    p = trouver(b["nom"])
    if p["loader"] != "Fabric":
        raise RuntimeError("Le Boost FPS marche sur les profils Fabric. Crée un profil Fabric.")
    P["busy"] = True
    try:
        ok = 0
        for slug in BOOST:
            try:
                installer_projet(slug, p, "mods", set())
                ok += 1
            except Exception:
                pass
        if not ok:
            raise RuntimeError("Aucun mod de performance compatible avec cette version.")
        statut("Boost FPS installé !", 100)
        return {"ok": True, "n": ok}
    finally:
        P["busy"] = False


def api_skinmod(b):
    P["busy"] = True
    try:
        p = trouver(b["nom"])
        if p["loader"] == "Vanilla":
            raise RuntimeError("Choisis un profil Fabric ou Forge.")
        installer_projet("customskinloader", p, "mods", set())
        return {"ok": True}
    finally:
        P["busy"] = False


def api_installes(a):
    p = trouver(a["nom"])
    return {"fichiers": lister(p, a.get("genre", "mods"))}


def api_retirer(b):
    p = trouver(b["nom"])
    nom_f = os.path.basename(b["fichier"])
    chemin = os.path.join(dossier_instance(p["nom"]), DOSSIERS_MR[b["genre"]][1], nom_f)
    if os.path.isfile(chemin):
        os.remove(chemin)
    return {"ok": True}


# ================================================================ serveurs / news / réglages
def api_ping(a):
    cible = separer_adresse(a["adresse"])
    try:
        d = ping_serveur(*cible)
        j = d.get("players", {})
        motd = re.sub(r"§.", "", texte_motd(d.get("description", ""))).replace("\n", " ").strip()
        return {"ok": True, "online": j.get("online", 0), "max": j.get("max", 0), "ms": d["ms"],
                "version": d.get("version", {}).get("name", ""), "motd": motd[:100]}
    except Exception:
        return {"ok": False}


def api_serveur_ajouter(b):
    if not separer_adresse(b["adresse"]):
        raise RuntimeError("Adresse invalide (ex : mc.exemple.fr ou mc.exemple.fr:25566).")
    l = lire_json(F_SERVEURS, [])
    l.append({"nom": b["nom"].strip()[:30] or b["adresse"], "adresse": b["adresse"].strip()})
    ecrire_json(F_SERVEURS, l)
    return {"ok": True}


def api_serveur_retirer(b):
    ecrire_json(F_SERVEURS, [s for s in lire_json(F_SERVEURS, []) if s["adresse"] != b["adresse"]])
    return {"ok": True}


def api_news(_):
    if time.time() - NEWS["t"] > 600 or not NEWS["data"]:
        req = urllib.request.Request("https://launchercontent.mojang.com/v2/javaPatchNotes.json", headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            entrees = json.load(r)["entries"]
        entrees.sort(key=lambda e: e.get("date", ""), reverse=True)
        out = []
        for e in entrees[:24]:
            img = (e.get("image") or {}).get("url", "")
            if img.startswith("/"):
                img = "https://launchercontent.mojang.com" + img
            out.append({"titre": e.get("title", "?"), "genre": e.get("type", ""), "version": e.get("version", ""),
                        "date": e.get("date", "")[:10], "resume": e.get("shortText", ""), "image": img})
        NEWS.update(t=time.time(), data=out)
    return {"news": NEWS["data"]}


def api_reglages(b):
    r = reglages()
    if "pseudo" in b:
        if not (3 <= len(b["pseudo"]) <= 16) or not b["pseudo"].replace("_", "").isalnum():
            raise RuntimeError("Pseudo invalide (3 à 16 caractères : lettres, chiffres, _).")
        r["pseudo"] = b["pseudo"]
    if "accent" in b and re.fullmatch(r"#[0-9a-fA-F]{6}", b["accent"]):
        r["accent"] = b["accent"]
    if "ram" in b:
        r["ram"] = max(1, min(64, int(b["ram"])))
    ecrire_json(F_REGLAGES, r)
    return {"ok": True}


def api_url(b):
    if re.match(r"https://[\w.\-]+(/|$)", b["url"]):
        webbrowser.open(b["url"])
    return {"ok": True}


def api_log(_):
    try:
        with open(os.path.join(DOSSIER, "launcher_log.txt"), encoding="utf-8", errors="replace") as f:
            return {"log": "".join(f.readlines()[-250:])}
    except OSError:
        return {"log": "Pas encore de journal. Lance une partie d'abord."}


def api_progress(_):
    ETAT["beat"] = time.time()
    ETAT["beats"] += 1
    err, P["error"] = P["error"], ""
    return {"status": P["status"], "pct": P["pct"], "running": P["running"], "error": err}


# ================================================================ compte Microsoft
def rafraichir_compte():
    global COMPTE
    cfg = lire_json(F_COMPTE, {})
    data = appeler_filtre(mll.microsoft_account.complete_refresh, client_id=cfg["client_id"],
                          client_secret=None, redirect_uri=cfg.get("redirect", "http://localhost"),
                          refresh_token=cfg["refresh_token"])
    if "name" not in data:
        raise RuntimeError("Session expirée, reconnecte-toi.")
    cfg["refresh_token"] = data.get("refresh_token", cfg["refresh_token"])
    ecrire_json(F_COMPTE, cfg)
    COMPTE = {"id": data["id"], "name": data["name"], "access_token": data["access_token"]}
    return COMPTE


def connexion(cid):
    global COMPTE
    resultat = {}

    class Recepteur(BaseHTTPRequestHandler):
        def do_GET(h):
            if "code=" in h.path or "error" in h.path:
                resultat["path"] = h.path
            h.send_response(200)
            h.send_header("Content-Type", "text/html; charset=utf-8")
            h.end_headers()
            h.wfile.write("<html><body style='font-family:sans-serif;text-align:center;margin-top:80px;"
                          "background:#0a0c10;color:#fff'><h1>Connexion terminée ✔</h1>"
                          "<p>Tu peux fermer cette page et retourner sur Lohyx Hub.</p></body></html>".encode())

        def log_message(h, *a):
            pass
    try:
        srv = HTTPServer(("localhost", 0), Recepteur)
        srv.timeout = 5
        redirect = f"http://localhost:{srv.server_port}"
        url, state, verifier = mll.microsoft_account.get_secure_login_data(cid, redirect)
        webbrowser.open(url)
        limite = time.time() + 180
        while "path" not in resultat:
            if time.time() > limite:
                raise RuntimeError("Temps écoulé : la connexion n'a pas été terminée.")
            srv.handle_request()
        srv.server_close()
        code = mll.microsoft_account.parse_auth_code_url(redirect + resultat["path"], state)
        data = appeler_filtre(mll.microsoft_account.complete_login, client_id=cid, client_secret=None,
                              redirect_uri=redirect, auth_code=code, code_verifier=verifier)
        if "name" not in data:
            raise RuntimeError("Connexion refusée. Ce compte possède-t-il Minecraft Java ?")
        ecrire_json(F_COMPTE, {"client_id": cid, "redirect": redirect, "refresh_token": data["refresh_token"]})
        COMPTE = {"id": data["id"], "name": data["name"], "access_token": data["access_token"]}
        LOGIN["msg"] = ""
    except Exception as e:
        LOGIN["msg"] = f"Connexion impossible : {e} (« Invalid app registration » = Microsoft n'a pas approuvé l'ID)"
    finally:
        LOGIN["busy"] = False


def api_login(b):
    if mll is None:
        raise RuntimeError("La bibliothèque minecraft-launcher-lib n'est pas installée.")
    if COMPTE:
        cfg = lire_json(F_COMPTE, {})
        cfg.pop("refresh_token", None)
        ecrire_json(F_COMPTE, cfg)
        globals()["COMPTE"] = None
        return {"ok": True}
    cid = (b.get("client_id") or CLIENT_ID or lire_json(F_COMPTE, {}).get("client_id", "")).strip()
    if not cid:
        raise RuntimeError("Ce launcher n'a pas encore de Client ID Microsoft approuvé : "
                           "il faut le coller une fois dans la ligne CLIENT_ID de LohyxHub.pyw.")
    LOGIN.update(busy=True, msg="Connecte-toi dans ton navigateur...")
    threading.Thread(target=connexion, args=(cid,), daemon=True).start()
    return {"ok": True}


def reconnexion_auto():
    try:
        rafraichir_compte()
    except Exception:
        pass


# ================================================================ mises à jour
def url_sure(u):
    p = urllib.parse.urlparse(u)
    return p.scheme == "https" or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost"))


def verifier_maj():
    base = UPDATE_URL.strip().rstrip("/")
    if not base:
        MAJ["erreur"] = "Aucune adresse de mise à jour (UPDATE_URL est vide)."
        return
    if not url_sure(base):
        MAJ["erreur"] = "L'adresse de mise à jour doit commencer par https://"
        return
    try:
        with urllib.request.urlopen(urllib.request.Request(base + "/version.json", headers=UA), timeout=15) as r:
            d = json.load(r)
        MAJ.update(version=str(d["version"]), notes=[str(n) for n in d.get("notes", [])][:12],
                   fichier=os.path.basename(d.get("fichier", "LohyxHub.pyw")),
                   sha256=str(d.get("sha256", "")).lower(), erreur="")
        MAJ["dispo"] = version_tuple(MAJ["version"]) > version_tuple(VERSION)
    except Exception as e:
        MAJ["erreur"] = f"Impossible de vérifier les mises à jour : {e}"


def api_maj_verifier(_):
    verifier_maj()
    return dict(MAJ)


def redemarrer():
    time.sleep(1.2)
    subprocess.Popen([sys.executable, CHEMIN_SCRIPT])
    os._exit(0)


def api_maj_installer(_):
    if not MAJ["dispo"]:
        raise RuntimeError("Aucune mise à jour disponible.")
    base = UPDATE_URL.strip().rstrip("/")
    if getattr(sys, "frozen", False) or not CHEMIN_SCRIPT.lower().endswith((".pyw", ".py")):
        webbrowser.open(base + "/")  # version .exe : on ouvre la page de téléchargement
        return {"ok": True, "manuel": True}
    P["busy"] = True
    try:
        statut("Téléchargement de la mise à jour...", 20)
        req = urllib.request.Request(base + "/" + urllib.parse.quote(MAJ["fichier"]), headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read(5_000_001)
        if len(data) > 5_000_000:
            raise RuntimeError("Fichier de mise à jour trop gros, annulé.")
        if MAJ["sha256"] and hashlib.sha256(data).hexdigest() != MAJ["sha256"]:
            raise RuntimeError("Le fichier téléchargé ne correspond pas à l'empreinte attendue : mise à jour annulée.")
        texte = data.decode("utf-8")
        compile(texte, MAJ["fichier"], "exec")
        if 'NOM = "Lohyx Hub"' not in texte:
            raise RuntimeError("Ce fichier n'est pas Lohyx Hub : mise à jour annulée.")
        shutil.copy2(CHEMIN_SCRIPT, CHEMIN_SCRIPT + ".bak")  # copie de secours
        tmp = CHEMIN_SCRIPT + ".new"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, CHEMIN_SCRIPT)
        statut("Mise à jour installée, redémarrage...", 100)
        threading.Thread(target=redemarrer, daemon=True).start()
        return {"ok": True, "version": MAJ["version"]}
    finally:
        P["busy"] = False


# ================================================================ jouer
def api_jouer(b):
    if mll is None:
        raise RuntimeError("La bibliothèque minecraft-launcher-lib n'est pas installée "
                           "(ouvre un terminal et tape : pip install minecraft-launcher-lib).")
    if P["busy"]:
        raise RuntimeError("Une opération est déjà en cours, patiente un instant.")
    p = trouver(b["nom"])
    cible = separer_adresse(b["adresse"]) if b.get("adresse") else None
    P.update(busy=True, pct=0, error="")
    threading.Thread(target=installer_et_lancer, args=(p, cible), daemon=True).start()
    return {"ok": True}


def installer_et_lancer(p, cible):
    version, loader = p["version"], p["loader"]
    try:
        r = reglages()
        jeu = dossier_instance(p["nom"])
        os.makedirs(os.path.join(jeu, "mods"), exist_ok=True)
        callback = {"setStatus": lambda t: statut(t),
                    "setMax": lambda v: P.update(max=max(v, 1)),
                    "setProgress": lambda v: P.update(pct=int(v / P["max"] * 100))}
        pseudo = r["pseudo"]
        options = {"username": pseudo,
                   "uuid": str(uuid.uuid3(uuid.NAMESPACE_OID, "OfflinePlayer:" + pseudo)),
                   "token": "", "gameDirectory": jeu,
                   "jvmArguments": [f"-Xmx{p.get('ram') or r['ram']}G", "-Xms1G"],
                   "customResolution": True, "resolutionWidth": "1280", "resolutionHeight": "720"}
        if COMPTE:
            statut("Vérification du compte...")
            c = rafraichir_compte()
            options.update({"username": c["name"], "uuid": c["id"], "token": c["access_token"]})
        if cible:
            if version_tuple(version) >= (1, 20):
                options["quickPlayMultiplayer"] = f"{cible[0]}:{cible[1]}"
            else:
                options["server"], options["port"] = cible[0], str(cible[1])

        mll.install.install_minecraft_version(version, DOSSIER, callback=callback)
        java_exe = None
        try:
            info = mll.runtime.get_version_runtime_information(version, DOSSIER)
            if info:
                statut("Installation de Java...")
                mll.runtime.install_jvm_runtime(info["name"], DOSSIER, callback=callback)
                java_exe = mll.runtime.get_executable_path(info["name"], DOSSIER)
                if java_exe:
                    options["executablePath"] = java_exe
        except Exception:
            pass
        id_lancement = version
        if loader == "Fabric":
            if not mll.fabric.is_minecraft_version_supported(version):
                raise RuntimeError(f"Fabric ne gère pas la version {version}.")
            statut("Installation de Fabric...")
            appeler(mll.fabric.install_fabric, version, DOSSIER, callback=callback, java=java_exe)
            id_lancement = f"fabric-loader-{mll.fabric.get_latest_loader_version()}-{version}"
        elif loader == "Forge":
            fv = mll.forge.find_forge_version(version)
            if not fv:
                raise RuntimeError(f"Forge n'existe pas pour la version {version}. Essaie 1.20.1.")
            if not mll.forge.supports_automatic_install(fv):
                raise RuntimeError("Cette version de Forge ne s'installe pas automatiquement.")
            statut("Installation de Forge (peut être long)...")
            appeler(mll.forge.install_forge_version, fv, DOSSIER, callback=callback, java=java_exe)
            id_lancement = mll.forge.forge_to_installed_version(fv)

        commande = mll.command.get_minecraft_command(id_lancement, DOSSIER, options)
        statut("Lancement de Minecraft...", 100)
        journal = open(os.path.join(DOSSIER, "launcher_log.txt"), "w", encoding="utf-8")
        debut = time.time()
        proc = subprocess.Popen(commande, cwd=jeu, stdout=journal, stderr=subprocess.STDOUT,
                                creationflags=0x08000000 if os.name == "nt" else 0)
        try:
            code = proc.wait(timeout=15)
            if code != 0:
                raise RuntimeError(f"Minecraft s'est fermé (code {code}). Regarde l'onglet Journal.")
        except subprocess.TimeoutExpired:
            statut("Minecraft est lancé ! Bon jeu 🎮")
            P["running"] = True
            threading.Thread(target=suivre_partie, args=(proc, p["nom"], debut), daemon=True).start()
    except Exception as e:
        statut("Erreur")
        P["error"] = str(e)
    finally:
        P["busy"] = False


def suivre_partie(proc, nom, debut):
    proc.wait()
    with VERROU:
        l = charger_profils()
        for x in l:
            if x["nom"] == nom:
                x["temps"] = x.get("temps", 0) + int(time.time() - debut)
        ecrire_json(F_PROFILS, l)
    P["running"] = False
    statut("Prêt", 0)


# ================================================================ serveur web local
ROUTES = {
    ("GET", "/api/state"): api_state, ("GET", "/api/progress"): api_progress,
    ("GET", "/api/versions"): api_versions, ("GET", "/api/verdict"): api_verdict,
    ("GET", "/api/perf"): api_perf, ("GET", "/api/chercher"): api_chercher,
    ("GET", "/api/installes"): api_installes, ("GET", "/api/news"): api_news,
    ("GET", "/api/log"): api_log, ("POST", "/api/ping"): api_ping,
    ("POST", "/api/profil/creer"): api_profil_creer, ("POST", "/api/profil/supprimer"): api_profil_supprimer,
    ("POST", "/api/profil/ouvrir"): api_profil_ouvrir, ("POST", "/api/sauvegarde"): api_sauvegarde,
    ("POST", "/api/installer"): api_installer, ("POST", "/api/retirer"): api_retirer,
    ("POST", "/api/boost"): api_boost, ("POST", "/api/skinmod"): api_skinmod,
    ("POST", "/api/serveur/ajouter"): api_serveur_ajouter, ("POST", "/api/serveur/retirer"): api_serveur_retirer,
    ("POST", "/api/reglages"): api_reglages, ("POST", "/api/login"): api_login,
    ("POST", "/api/jouer"): api_jouer, ("POST", "/api/url"): api_url,
    ("POST", "/api/maj/verifier"): api_maj_verifier, ("POST", "/api/maj/installer"): api_maj_installer,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def envoyer(self, code, corps, genre="application/json; charset=utf-8"):
        if not isinstance(corps, bytes):
            corps = json.dumps(corps, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", genre)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, methode):
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self.envoyer(403, {"erreur": "interdit"})
        u = urllib.parse.urlparse(self.path)
        args = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if methode == "GET" and u.path == "/":
            if args.get("t") != TOKEN:
                return self.envoyer(403, {"erreur": "interdit"})
            return self.envoyer(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        if self.headers.get("X-Token") != TOKEN:
            return self.envoyer(403, {"erreur": "interdit"})
        f = ROUTES.get((methode, u.path))
        if not f:
            return self.envoyer(404, {"erreur": "inconnu"})
        try:
            if methode == "POST":
                n = int(self.headers.get("Content-Length", 0))
                args = json.loads(self.rfile.read(n) or b"{}")
            self.envoyer(200, f(args))
        except Exception as e:
            self.envoyer(400, {"erreur": str(e) or e.__class__.__name__})


def ouvrir_fenetre(url):
    pf = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
          os.environ.get("LocalAppData", "")]
    candidats = [os.path.join(b, *c) for c in (("Microsoft", "Edge", "Application", "msedge.exe"),
                                              ("Google", "Chrome", "Application", "chrome.exe")) for b in pf if b]
    for exe in candidats:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1240,780", "--no-first-run",
                              "--user-data-dir=" + os.path.join(DOSSIER, "fenetre")])
            return
    webbrowser.open(url)


def main():
    os.makedirs(DOSSIER, exist_ok=True)
    threading.Thread(target=detecter_specs, daemon=True).start()
    if UPDATE_URL.strip():
        threading.Thread(target=verifier_maj, daemon=True).start()
    if mll and lire_json(F_COMPTE, {}).get("refresh_token"):
        threading.Thread(target=reconnexion_auto, daemon=True).start()
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{serveur.server_address[1]}/?t={TOKEN}"
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    ouvrir_fenetre(url)
    debut = time.time()
    while True:  # on quitte quand la fenêtre est fermée
        time.sleep(2)
        if ETAT["beats"] == 0 and time.time() - debut > 90:
            break
        if ETAT["beats"] and time.time() - ETAT["beat"] > 25 and not P["busy"]:
            break
    serveur.shutdown()


HTML = r"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Lohyx Hub</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9Ii01NiAtNjQgMTEyIDExNCI+PHJlY3QgeD0iLTU2IiB5PSItNjQiIHdpZHRoPSIxMTIiIGhlaWdodD0iMTE0IiByeD0iMjQiIGZpbGw9IiMwYjBkMTIiLz48cG9seWdvbiBwb2ludHM9Ii0yNi4wLC0xNS4wIDAuMCwwLjAgMC4wLDMwLjAgLTI2LjAsMTUuMCIgZmlsbD0iIzdjNWNmZiIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLDAuMCAyNi4wLC0xNS4wIDI2LjAsMTUuMCAwLjAsMzAuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLC0zMC4wIDI2LjAsLTE1LjAgMC4wLDAuMCAtMjYuMCwtMTUuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iLTUyLjAsMC4wIC0yNi4wLDE1LjAgLTI2LjAsNDUuMCAtNTIuMCwzMC4wIiBmaWxsPSIjN2M1Y2ZmIi8+PHBvbHlnb24gcG9pbnRzPSItMjYuMCwxNS4wIDAuMCwwLjAgMC4wLDMwLjAgLTI2LjAsNDUuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iLTI2LjAsLTE1LjAgMC4wLDAuMCAtMjYuMCwxNS4wIC01Mi4wLDAuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLDAuMCAyNi4wLDE1LjAgMjYuMCw0NS4wIDAuMCwzMC4wIiBmaWxsPSIjN2M1Y2ZmIi8+PHBvbHlnb24gcG9pbnRzPSIyNi4wLDE1LjAgNTIuMCwwLjAgNTIuMCwzMC4wIDI2LjAsNDUuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iMjYuMCwtMTUuMCA1Mi4wLDAuMCAyNi4wLDE1LjAgMC4wLDAuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iLTIwLjMsLTQ3LjcgMC4wLC0zNi4wIDAuMCwtMTIuNiAtMjAuMywtMjQuMyIgZmlsbD0iIzdjNWNmZiIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLC0zNi4wIDIwLjMsLTQ3LjcgMjAuMywtMjQuMyAwLjAsLTEyLjYiIGZpbGw9IiMzYjJhYTgiLz48cG9seWdvbiBwb2ludHM9IjAuMCwtNTkuNCAyMC4zLC00Ny43IDAuMCwtMzYuMCAtMjAuMywtNDcuNyIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjwvc3ZnPg==">
<style>
:root{--a:#1bd96a;--bg:#090b0f;--panel:rgba(255,255,255,.05);--line:rgba(255,255,255,.09);--txt:#f3f6fa;--mut:#8d98a8;--vert:#22c55e;--jaune:#facc15;--orange:#fb923c;--rouge:#ef4444}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:var(--bg);color:var(--txt);font-family:"Segoe UI Variable","Segoe UI",system-ui,sans-serif;overflow:hidden}
::-webkit-scrollbar{width:9px}::-webkit-scrollbar-thumb{background:rgba(255,255,255,.14);border-radius:9px}
.orb{position:fixed;border-radius:50%;filter:blur(120px);z-index:0;animation:fl 20s ease-in-out infinite alternate}
.o1{width:540px;height:540px;background:var(--a);opacity:.26;top:-180px;left:140px}
.o2{width:480px;height:480px;background:#6d4aff;opacity:.25;bottom:-200px;right:-90px;animation-delay:-7s}
.o3{width:320px;height:320px;background:#00b7ff;opacity:.13;top:42%;left:46%;animation-delay:-12s}
@keyframes fl{to{transform:translate(80px,55px) scale(1.18)}}
#app{position:relative;z-index:1;display:flex;height:100%}
aside{width:240px;padding:22px 14px 16px;display:flex;flex-direction:column;border-right:1px solid var(--line);background:rgba(7,9,13,.6);backdrop-filter:blur(20px)}
.logo{display:flex;align-items:center;gap:11px;padding:0 10px 22px}
.lt{font-size:25px;font-weight:900;letter-spacing:3px;background:linear-gradient(90deg,var(--a),#9a8bff);-webkit-background-clip:text;background-clip:text;color:transparent;line-height:1.1}
.lt small{display:block;font-size:10px;letter-spacing:7px;margin-top:2px;-webkit-text-fill-color:var(--mut)}
.logo svg{filter:drop-shadow(0 0 10px color-mix(in srgb,var(--a) 55%,transparent));flex:none}
nav{flex:1;display:flex;flex-direction:column;gap:3px}
nav button{display:flex;align-items:center;gap:12px;padding:11px 14px;border:0;border-radius:12px;background:transparent;color:var(--mut);font-size:14.5px;font-weight:600;cursor:pointer;text-align:left;transition:.18s}
nav button span{width:30px;height:30px;display:grid;place-items:center;border-radius:9px;background:rgba(255,255,255,.05);font-size:15px}
nav button:hover{background:rgba(255,255,255,.06);color:var(--txt)}
nav button.on{background:linear-gradient(90deg,color-mix(in srgb,var(--a) 22%,transparent),transparent);color:var(--txt);box-shadow:inset 3px 0 0 var(--a)}
nav button.on span{background:var(--a);color:#06100a}
#me{display:flex;align-items:center;gap:11px;padding:12px;border-radius:14px;background:var(--panel);border:1px solid var(--line)}
#me img{width:40px;height:40px;border-radius:10px;image-rendering:pixelated}
#me2 .btn{width:100%;margin-top:9px;padding:12px}#me b{display:block;font-size:14px}#me small{color:var(--mut);font-size:12px}
main{flex:1;display:flex;flex-direction:column;min-width:0}
#maj{display:none;align-items:center;gap:12px;padding:12px 28px;border-bottom:1px solid var(--line);background:linear-gradient(90deg,color-mix(in srgb,var(--a) 22%,transparent),rgba(255,255,255,.03));font-size:14px}
#page{flex:1;overflow:auto;padding:30px 36px}
footer{display:flex;align-items:center;gap:16px;padding:0 28px;height:48px;border-top:1px solid var(--line);background:rgba(7,9,13,.6);backdrop-filter:blur(20px);font-size:13px;color:var(--mut)}
#fbarw{flex:0 0 280px;height:7px;border-radius:7px;background:rgba(255,255,255,.08);overflow:hidden}
#fbar{height:100%;width:0;background:linear-gradient(90deg,var(--a),#9a8bff);transition:width .4s}
h1{font-size:30px;font-weight:800;letter-spacing:-.5px}h2{font-size:22px;font-weight:800;margin-bottom:6px}h3{font-size:15px;margin:22px 0 10px;color:var(--mut);text-transform:uppercase;letter-spacing:2px;font-size:12px}
.mut{color:var(--mut)}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.sp{flex:1}
.glass{background:var(--panel);border:1px solid var(--line);border-radius:20px;backdrop-filter:blur(14px)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px}
.card{padding:18px;transition:.2s}.card:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--a) 50%,transparent)}
.eyebrow{font-size:11px;letter-spacing:4px;color:var(--a);font-weight:800;margin-bottom:8px}
.hero{display:flex;gap:30px;padding:32px;align-items:center;flex-wrap:wrap;background:linear-gradient(135deg,color-mix(in srgb,var(--a) 14%,transparent),rgba(255,255,255,.03))}
.hero>div:first-child{flex:1;min-width:300px}.hero .meta{color:var(--mut);margin:6px 0 22px}
.btn{border:1px solid var(--line);background:rgba(255,255,255,.07);color:var(--txt);padding:10px 16px;border-radius:12px;font-size:13.5px;font-weight:700;cursor:pointer;transition:.15s}
.btn:hover{background:rgba(255,255,255,.14)}.btn.pri{background:var(--a);color:#06100a;border-color:transparent}.btn.pri:hover{filter:brightness(1.1)}
.btn.red{background:rgba(239,68,68,.16);color:#ff8f8f}.btn.red:hover{background:rgba(239,68,68,.3)}
.play{border:0;border-radius:16px;padding:17px 52px;font-size:19px;font-weight:900;color:#07110a;cursor:pointer;letter-spacing:2px;transition:.2s}
.play.sm{padding:9px 20px;font-size:13px;border-radius:11px;letter-spacing:1px}.play:hover{transform:translateY(-2px) scale(1.04)}
.v-vert.play{background:var(--vert);box-shadow:0 10px 36px rgba(34,197,94,.45)}.v-jaune.play{background:var(--jaune);box-shadow:0 10px 36px rgba(250,204,21,.4)}
.v-orange.play{background:var(--orange);box-shadow:0 10px 36px rgba(251,146,60,.42)}.v-rouge.play{background:var(--rouge);color:#fff;box-shadow:0 10px 36px rgba(239,68,68,.45)}
.play.sm{box-shadow:none!important}
.verdict{margin-top:18px;padding:12px 16px;border-radius:14px;font-size:14px;border:1px solid;max-width:520px;line-height:1.45}
.verdict.v-vert{border-color:var(--vert);background:rgba(34,197,94,.1)}.verdict.v-jaune{border-color:var(--jaune);background:rgba(250,204,21,.09)}
.verdict.v-orange{border-color:var(--orange);background:rgba(251,146,60,.1)}.verdict.v-rouge{border-color:var(--rouge);background:rgba(239,68,68,.1)}
.dot{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:7px;vertical-align:middle}
.bar{height:9px;border-radius:9px;background:rgba(255,255,255,.08);overflow:hidden;margin:6px 0 14px}.bar i{display:block;height:100%;border-radius:9px;transition:width .6s}
.bl{display:flex;justify-content:space-between;font-size:13px}.bl b{white-space:nowrap}.bl span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-left:12px}
.btn.ic{padding:9px 13px}.nw{flex-wrap:nowrap!important}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-top:16px}
.stat{padding:18px}.stat b{display:block;font-size:26px;font-weight:800;color:var(--a)}.stat span{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:1.5px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 0}.chip{padding:8px 15px;border-radius:30px;border:1px solid var(--line);background:rgba(255,255,255,.05);cursor:pointer;font-size:13px;font-weight:600}.chip.on{background:var(--a);color:#06100a;border-color:transparent}
input,select{width:100%;padding:12px 14px;border-radius:12px;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--txt);font-size:14px;outline:none;font-family:inherit}
input:focus,select:focus{border-color:var(--a)}select option{background:#14171d}input[type=range]{padding:0;accent-color:var(--a)}
label{display:block;margin:14px 0 6px;font-size:12px;color:var(--mut);letter-spacing:1px;text-transform:uppercase}
.seg{display:flex;gap:6px}.seg button{flex:1;padding:10px;border-radius:11px;border:1px solid var(--line);background:rgba(255,255,255,.05);color:var(--txt);font-weight:700;cursor:pointer}.seg button.on{background:var(--a);color:#06100a;border-color:transparent}
.tabs{display:flex;gap:6px;margin:14px 0}.tabs button{padding:9px 18px;border-radius:30px;border:1px solid var(--line);background:transparent;color:var(--mut);font-weight:700;cursor:pointer}.tabs button.on{background:var(--a);color:#06100a;border-color:transparent}
.mod{display:flex;gap:14px;padding:14px}.mod img{width:56px;height:56px;border-radius:13px;background:rgba(255,255,255,.07);object-fit:cover;flex:none}
.mod h4{font-size:15px}.mod p{font-size:12.5px;color:var(--mut);margin:3px 0 9px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.news img{width:100%;height:150px;object-fit:cover;border-radius:14px;margin-bottom:12px;background:rgba(255,255,255,.05)}
.tag{font-size:11px;padding:3px 9px;border-radius:20px;background:rgba(255,255,255,.1);color:var(--mut);font-weight:700}
table{width:100%;border-collapse:collapse}th,td{padding:13px 14px;text-align:left;border-bottom:1px solid var(--line);font-size:14px}th{color:var(--mut);font-size:12px;letter-spacing:1.5px;text-transform:uppercase}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(6px);display:none;place-items:center;z-index:50}.modal.on{display:grid}
.box{width:440px;max-width:92vw;padding:28px;background:#12151b}
#toasts{position:fixed;right:22px;bottom:64px;display:flex;flex-direction:column;gap:9px;z-index:60}
.toast{padding:13px 18px;border-radius:13px;background:#171b22;border:1px solid var(--a);max-width:380px;font-size:13.5px;animation:in .3s}.toast.bad{border-color:var(--rouge)}
@keyframes in{from{transform:translateX(40px);opacity:0}}
pre{padding:16px;border-radius:14px;background:rgba(0,0,0,.35);font-size:12px;line-height:1.5;white-space:pre-wrap;max-height:62vh;overflow:auto;color:#b7c2d1}
.sw{width:34px;height:34px;border-radius:50%;cursor:pointer;border:3px solid transparent}.sw.on{border-color:#fff}
.pill{display:inline-flex;align-items:center;font-size:13px;font-weight:700}
</style></head>
<body>
<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
<div id="app">
<aside><div class="logo"><svg viewBox="-56 -64 112 114" width="46" height="47" aria-hidden="true"><defs><linearGradient id="ut" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#d6ffe7"/><stop offset="1" style="stop-color:var(--a)"/></linearGradient><linearGradient id="ul" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8d70ff"/><stop offset="1" stop-color="#5a3fe0"/></linearGradient><linearGradient id="ur" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5a3fe0"/><stop offset="1" stop-color="#2d1f8f"/></linearGradient></defs><polygon points="-26.0,-15.0 0.0,0.0 0.0,30.0 -26.0,15.0" fill="url(#ul)"/><polygon points="0.0,0.0 26.0,-15.0 26.0,15.0 0.0,30.0" fill="url(#ur)"/><polygon points="0.0,-30.0 26.0,-15.0 0.0,0.0 -26.0,-15.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="-52.0,0.0 -26.0,15.0 -26.0,45.0 -52.0,30.0" fill="url(#ul)"/><polygon points="-26.0,15.0 0.0,0.0 0.0,30.0 -26.0,45.0" fill="url(#ur)"/><polygon points="-26.0,-15.0 0.0,0.0 -26.0,15.0 -52.0,0.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="0.0,0.0 26.0,15.0 26.0,45.0 0.0,30.0" fill="url(#ul)"/><polygon points="26.0,15.0 52.0,0.0 52.0,30.0 26.0,45.0" fill="url(#ur)"/><polygon points="26.0,-15.0 52.0,0.0 26.0,15.0 0.0,0.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="-20.3,-47.7 0.0,-36.0 0.0,-12.6 -20.3,-24.3" fill="url(#ul)"/><polygon points="0.0,-36.0 20.3,-47.7 20.3,-24.3 0.0,-12.6" fill="url(#ur)"/><polygon points="0.0,-59.4 20.3,-47.7 0.0,-36.0 -20.3,-47.7" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/></svg><div class="lt">LOHYX<small>HUB</small></div></div><nav id="nav"></nav><div id="me"></div><div id="me2"></div></aside>
<main><div id="maj" class="majbar"></div><div id="page"></div>
<footer><span id="fst">Prêt</span><div id="fbarw"><div id="fbar"></div></div><span class="sp"></span><span id="fpc"></span></footer></main>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)fermer()"><div class="glass box" id="mbox"></div></div>
<div id="toasts"></div>
<script>
const T=new URLSearchParams(location.search).get('t'),$=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Token':T,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 const d=await r.json();if(!r.ok)throw new Error(d.erreur||'Erreur');return d}
const qs=o=>'?'+new URLSearchParams(o);
function toast(m,bad){const d=document.createElement('div');d.className='toast'+(bad?' bad':'');d.textContent=m;$('#toasts').appendChild(d);setTimeout(()=>d.remove(),4800)}
async function run(fn){try{return await fn()}catch(e){toast(e.message,true)}}
const fmt=n=>Number(n).toLocaleString('fr-FR');
const duree=s=>{s=s||0;const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?h+' h '+m+' min':m+' min'};
const VC={vert:'#22c55e',jaune:'#facc15',orange:'#fb923c',rouge:'#ef4444'};
const NAV=[['accueil','🏠','Accueil'],['profils','🎮','Profils'],['mods','🧩','Mods & packs'],['serveurs','🌐','Serveurs'],['skins','🎨','Skins'],['actus','📰','Actualités'],['perf','⚡','Performance'],['journal','🧾','Journal'],['reglages','⚙️','Réglages']];
let lb=false,S={profils:[],serveurs:[],reglages:{},specs:{},compte:null,login:{}},page='accueil',sel=0,genre='mods',R=[],last={running:false,busy:false},timerJ=null;
function cur(){return S.profils[Math.min(sel,S.profils.length-1)]}
function renderNav(){$('#nav').innerHTML=NAV.map(([k,i,t])=>`<button class="${k==page?'on':''}" onclick="go('${k}')"><span>${i}</span>${t}</button>`).join('')}
function go(p){page=p;clearInterval(timerJ);renderNav();render()}
function applyAccent(){document.documentElement.style.setProperty('--a',S.reglages.accent||'#1bd96a')}
function renderMe(){const n=S.reglages.pseudo||'Joueur',c=S.compte;
 $('#me').innerHTML=`<img src="https://mc-heads.net/avatar/${encodeURIComponent(c?c.name:n)}/64" onerror="this.style.visibility='hidden'"><div><b>${esc(c?c.name:n)}</b><small>${c?'Compte Microsoft ✔':'Mode hors-ligne'}</small></div>`;
 $('#me2').innerHTML=c?'':'<button class="btn pri" onclick="login()">🔐 Se connecter à Minecraft</button>'}
async function charger(){S=await api('/api/state');applyAccent();renderMe();renderMaj();render()}
function renderMaj(){const m=S.maj,b=$('#maj');if(m&&m.dispo){b.style.display='flex';b.innerHTML=`<span>🚀 <b>Mise à jour ${esc(m.version)}</b> disponible${m.notes.length?' — '+esc(m.notes[0]):''}</span><span class="sp"></span><button class="btn pri" onclick="majInstaller()">Mettre à jour</button><button class="btn" onclick="$('#maj').style.display='none'">Plus tard</button>`}else b.style.display='none'}
async function majInstaller(){toast('Téléchargement de la mise à jour…');const d=await run(()=>api('/api/maj/installer',{}));if(!d)return;
 if(d.manuel)return toast('La page de téléchargement s\'ouvre dans ton navigateur.');
 document.body.innerHTML='<div style="display:grid;place-items:center;height:100%;text-align:center;font-size:22px;line-height:1.7">🚀 Mise à jour installée !<br><span style="font-size:14px;color:#8d98a8">Lohyx Hub redémarre dans une nouvelle fenêtre.<br>Ferme celle-ci si elle reste ouverte.</span></div>';setTimeout(()=>window.close(),2500)}
function majVerifier(){run(async()=>{const d=await api('/api/maj/verifier',{});await charger();toast(d.erreur?d.erreur:d.dispo?'Mise à jour '+d.version+' disponible !':'Tu as la dernière version ✔',!!d.erreur)})}
function render(){({accueil:pAccueil,profils:pProfils,mods:pMods,serveurs:pServeurs,skins:pSkins,actus:pActus,perf:pPerf,journal:pJournal,reglages:pReglages})[page]()}
function vbadge(v){return `<span class="pill"><i class="dot" style="background:${VC[v.niveau]}"></i>${v.label}</span>`}
function bars(v){return v.details.map(d=>`<div class="bl"><b>${d.nom}</b><span class="mut">${esc(d.info)}</span></div><div class="bar"><i style="width:${Math.round(d.ratio*100)}%;background:${d.ratio>=.95?VC.vert:d.ratio>=.75?VC.jaune:d.ratio>=.55?VC.orange:VC.rouge}"></i></div>`).join('')}

/* ---------- Accueil ---------- */
function pAccueil(){const P=S.profils,p=cur(),tot=P.reduce((a,x)=>a+(x.temps||0),0),mods=P.reduce((a,x)=>a+x.nb_mods,0);let h;
 if(!p)h=`<div class="glass hero"><div><div class="eyebrow">BIENVENUE SUR LOHYX HUB</div><h1>Crée ton premier profil</h1><p class="meta">Choisis une version de Minecraft : tout s'installe tout seul.</p><button class="play v-vert" onclick="nouveauProfil()">＋ NOUVEAU PROFIL</button></div></div>`;
 else{const v=p.verdict;h=`<div class="glass hero"><div><div class="eyebrow">PROFIL SÉLECTIONNÉ</div><h1>${esc(p.nom)}</h1><div class="meta">Minecraft ${esc(p.version)} · ${p.loader} · ${p.nb_mods} mods · ${p.ram||S.reglages.ram} Go de RAM</div>
 <button class="play v-${v.niveau}" onclick="jouer(${sel})">▶ JOUER</button><div class="verdict v-${v.niveau}"><b>${v.label}</b> — ${esc(v.message)}</div></div>
 <div style="width:290px"><div class="mut" style="font-size:12px;letter-spacing:2px;margin-bottom:10px">PUISSANCE DU PC POUR CE PROFIL</div>${bars(v)}</div></div>
 <div class="chips">${P.map((x,i)=>`<span class="chip ${i==sel?'on':''}" onclick="sel=${i};render()">${esc(x.nom)}</span>`).join('')}</div>`}
 if(!S.compte)h+=`<div class="glass card row" style="margin-top:16px"><div><b>🔐 Joue sur les serveurs officiels</b><div class="mut" style="font-size:13px;margin-top:2px">Connecte-toi avec le compte Microsoft qui possède Minecraft Java.</div></div><span class="sp"></span><button class="btn pri" onclick="login()">Se connecter à votre compte Minecraft</button></div>`;
 h+=`<div class="stats"><div class="glass stat"><b>${P.length}</b><span>Profils</span></div><div class="glass stat"><b>${mods}</b><span>Mods installés</span></div><div class="glass stat"><b>${duree(tot)}</b><span>Temps de jeu</span></div></div><h3>Dernières actualités</h3><div class="grid" id="ap"><div class="mut">Chargement…</div></div>`;
 $('#page').innerHTML=h;
 api('/api/news').then(d=>{if(page=='accueil'&&$('#ap'))$('#ap').innerHTML=d.news.slice(0,3).map(newsCard).join('')}).catch(()=>{if($('#ap'))$('#ap').innerHTML='<div class="mut">Actualités indisponibles (pas de connexion ?).</div>'})}
function newsCard(n){return `<div class="glass card news" onclick="url('https://minecraft.wiki/w/Java_Edition_${encodeURIComponent((n.version||'').replace(/ /g,'_'))}')" style="cursor:pointer">${n.image?`<img src="${esc(n.image)}" onerror="this.remove()">`:''}<div class="row"><span class="tag">${n.genre=='snapshot'?'Snapshot':'Version'}</span><span class="mut" style="font-size:12px">${esc(n.date)}</span></div><h4 style="margin:8px 0 4px">${esc(n.titre)}</h4><p class="mut" style="font-size:13px">${esc(n.resume).slice(0,140)}</p></div>`}
function url(u){run(()=>api('/api/url',{url:u}))}
function jouer(i,adresse){const p=S.profils[i];run(async()=>{await api('/api/jouer',{nom:p.nom,adresse});toast('Préparation de '+p.nom+'…')})}

/* ---------- Profils ---------- */
function pProfils(){const P=S.profils;
 $('#page').innerHTML=`<div class="row"><h1>Mes profils</h1><span class="sp"></span><button class="btn pri" onclick="nouveauProfil()">＋ Nouveau profil</button></div><p class="mut" style="margin:6px 0 20px">Le bouton Jouer change de couleur selon la puissance de ton PC pour ce profil.</p>
 <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(370px,1fr))">${P.length?P.map((p,i)=>`<div class="glass card"><div class="row nw"><h2 style="margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.nom)}</h2><span class="sp"></span>${vbadge(p.verdict)}</div><div class="mut" style="margin:6px 0 14px;font-size:13px">Minecraft ${esc(p.version)} · ${p.loader} · ${p.nb_mods} mods${p.shaders?' · shaders':''}<br>${p.ram||S.reglages.ram} Go de RAM · ${duree(p.temps)} de jeu</div>
 <div class="row"><button class="play sm v-${p.verdict.niveau}" onclick="jouer(${i})">▶ JOUER</button><button class="btn ic" title="Mods" onclick="sel=${i};go('mods')">🧩</button><button class="btn ic" title="Ouvrir le dossier" onclick="ouvrir(${i})">📁</button><button class="btn ic" title="Sauvegarder les mondes" onclick="sauver(${i})">💾</button><button class="btn red ic" title="Supprimer" onclick="suppr(${i})">🗑</button></div></div>`).join(''):'<div class="mut">Aucun profil. Clique sur « Nouveau profil ».</div>'}</div>`}
const ouvrir=i=>run(()=>api('/api/profil/ouvrir',{nom:S.profils[i].nom}));
const sauver=i=>run(async()=>{const d=await api('/api/sauvegarde',{nom:S.profils[i].nom});toast('Sauvegarde créée ✔')});
function suppr(i){const p=S.profils[i];if(confirm('Supprimer « '+p.nom+' » ?\nSes mondes et ses mods seront effacés.'))run(async()=>{await api('/api/profil/supprimer',{nom:p.nom});sel=0;await charger()})}
function modal(h){$('#mbox').innerHTML=h;$('#modal').classList.add('on')}
function fermer(){$('#modal').classList.remove('on')}
async function nouveauProfil(){const v=await run(()=>api('/api/versions'));if(!v)return;const max=Math.max(2,Math.min(32,Math.floor((S.specs.ram||8)-2)));
 modal(`<h2>Nouveau profil</h2><label>Nom</label><input id="m-nom" maxlength="30" placeholder="Mon aventure"><label>Type</label><div class="seg" id="m-type">${['Vanilla','Fabric','Forge'].map((t,i)=>`<button class="${i==1?'on':''}" onclick="seg(this)">${t}</button>`).join('')}</div>
 <label>Version de Minecraft</label><select id="m-ver" onchange="apercu()">${v.versions.map(x=>`<option>${x}</option>`).join('')}</select>
 <label>Mémoire : <b id="m-rv">${Math.min(4,max)}</b> Go</label><input type="range" id="m-ram" min="1" max="${max}" value="${Math.min(4,max)}" oninput="$('#m-rv').textContent=this.value">
 <div id="m-v" style="margin-top:16px"></div><div class="row" style="margin-top:20px"><span class="sp"></span><button class="btn" onclick="fermer()">Annuler</button><button class="btn pri" onclick="creer()">Créer</button></div>`);apercu()}
function seg(b){b.parentNode.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');apercu()}
function apercu(){const l=document.querySelector('#m-type .on').textContent,v=$('#m-ver').value;api('/api/verdict'+qs({version:v,loader:l})).then(d=>{if($('#m-v'))$('#m-v').innerHTML=`<div class="verdict v-${d.niveau}" style="margin:0"><b>${d.label}</b> — ${esc(d.message)}</div>`}).catch(()=>{})}
function creer(){run(async()=>{await api('/api/profil/creer',{nom:$('#m-nom').value,version:$('#m-ver').value,loader:document.querySelector('#m-type .on').textContent,ram:$('#m-ram').value});fermer();sel=S.profils.length;await charger();go('profils');toast('Profil créé ✔')})}

/* ---------- Mods ---------- */
function pMods(){const p=cur();if(!p){$('#page').innerHTML='<h1>Mods & packs</h1><p class="mut" style="margin-top:10px">Crée d\'abord un profil.</p>';return}
 $('#page').innerHTML=`<h1>Mods, shaders & packs</h1><div class="row" style="margin-top:14px"><div style="width:240px"><select onchange="sel=this.value;pMods()">${S.profils.map((x,i)=>`<option value="${i}" ${i==sel?'selected':''}>${esc(x.nom)} (${x.version} ${x.loader})</option>`).join('')}</select></div>${vbadge(p.verdict)}</div>
 <div class="tabs">${[['mods','Mods'],['shaders','Shaders'],['packs','Packs de ressources']].map(([k,t])=>`<button class="${k==genre?'on':''}" onclick="genre='${k}';pMods()">${t}</button>`).join('')}</div>
 ${genre=='mods'&&p.loader=='Fabric'?`<div class="glass card row" style="margin-bottom:14px"><div><b>🚀 Boost FPS</b><div class="mut" style="font-size:13px">Installe Sodium, Lithium, FerriteCore, EntityCulling et ModernFix en un clic.</div></div><span class="sp"></span><button class="btn pri" onclick="boost()">Installer</button></div>`:''}
 ${genre=='shaders'?`<div class="mut" style="font-size:13px;margin-bottom:12px">Les shaders demandent le mod Iris (cherche « iris » dans l'onglet Mods) et une bonne carte graphique.</div>`:''}
 <div class="row"><input id="q" placeholder="Rechercher… (ex : sodium)" onkeydown="if(event.key=='Enter')chercher()" style="flex:1"><button class="btn pri" onclick="chercher()">Rechercher</button></div>
 <div class="grid" id="res" style="margin-top:16px"></div><h3>Déjà installés</h3><div id="inst"></div>`;
 chercher();installes()}
function chercher(){const p=cur();$('#res').innerHTML='<div class="mut">Recherche…</div>';
 api('/api/chercher'+qs({nom:p.nom,genre,q:$('#q').value})).then(d=>{R=d.resultats;$('#res').innerHTML=R.length?R.map((m,i)=>`<div class="glass mod"><img src="${esc(m.icone)}" onerror="this.style.visibility='hidden'"><div><h4>${esc(m.titre)}</h4><p>${esc(m.desc)}</p><div class="row"><button class="btn pri" onclick="inst(${i},this)">Installer</button><span class="mut" style="font-size:12px">⬇ ${fmt(m.dl)}</span></div></div></div>`).join(''):'<div class="mut">Aucun résultat pour cette version.</div>'}).catch(e=>{$('#res').innerHTML=`<div class="mut">${esc(e.message)}</div>`})}
function inst(i,b){const p=cur();b.textContent='…';b.disabled=true;run(async()=>{try{await api('/api/installer',{nom:p.nom,id:R[i].id,genre});b.textContent='Installé ✔';toast(R[i].titre+' installé ✔');await refresh()}finally{b.disabled=false}})}
function boost(){const p=cur();toast('Installation du Boost FPS…');run(async()=>{const d=await api('/api/boost',{nom:p.nom});toast('Boost FPS : '+d.n+' mods installés ✔');await refresh()})}
async function refresh(){await charger();if(page=='mods')installes()}
function installes(){const p=cur();api('/api/installes'+qs({nom:p.nom,genre})).then(d=>{$('#inst').innerHTML=d.fichiers.length?d.fichiers.map(f=>`<div class="glass row" style="padding:10px 16px;margin-bottom:6px"><span style="font-size:13.5px">${esc(f)}</span><span class="sp"></span><button class="btn red" onclick="retirer('${esc(f).replace(/'/g,'')}')">Retirer</button></div>`).join(''):'<div class="mut">Rien d\'installé ici.</div>'}).catch(()=>{})}
function retirer(f){const p=cur();run(async()=>{await api('/api/retirer',{nom:p.nom,genre,fichier:f});await refresh()})}

/* ---------- Serveurs ---------- */
function pServeurs(){const P=S.profils;
 $('#page').innerHTML=`<div class="row"><h1>Serveurs</h1><span class="sp"></span><button class="btn" onclick="pServeurs()">↻ Actualiser</button><button class="btn pri" onclick="ajoutSrv()">＋ Ajouter</button></div>
 <div class="row" style="margin:14px 0"><span class="mut">Rejoindre avec le profil</span><div style="width:240px"><select id="sp-p">${P.map((x,i)=>`<option value="${i}">${esc(x.nom)}</option>`).join('')}</select></div></div>
 <div class="grid">${S.serveurs.length?S.serveurs.map((s,i)=>`<div class="glass card"><div class="row"><h2 style="margin:0">${esc(s.nom)}</h2><span class="sp"></span><span class="pill" id="sv${i}"><i class="dot" style="background:#667"></i>…</span></div><div class="mut" style="font-size:13px;margin:4px 0 12px">${esc(s.adresse)}</div><div id="sm${i}" class="mut" style="font-size:13px;min-height:20px;margin-bottom:12px"></div><div class="row"><button class="btn pri" onclick="rejoindre(${i})">Rejoindre</button><button class="btn red" onclick="retSrv(${i})">Retirer</button></div></div>`).join(''):'<div class="mut">Aucun serveur. Clique sur « Ajouter » (ex : mc.hypixel.net).</div>'}</div>`;
 S.serveurs.forEach((s,i)=>api('/api/ping',{adresse:s.adresse}).then(d=>{if(!$('#sv'+i))return;$('#sv'+i).innerHTML=d.ok?`<i class="dot" style="background:${VC.vert}"></i>${d.online}/${d.max} · ${d.ms} ms`:`<i class="dot" style="background:${VC.rouge}"></i>Hors ligne`;if(d.ok)$('#sm'+i).textContent=d.motd+(d.version?'  ·  '+d.version:'')}))}
function ajoutSrv(){modal(`<h2>Ajouter un serveur</h2><label>Nom</label><input id="s-n" placeholder="Mon serveur"><label>Adresse</label><input id="s-a" placeholder="mc.exemple.fr"><div class="row" style="margin-top:20px"><span class="sp"></span><button class="btn" onclick="fermer()">Annuler</button><button class="btn pri" onclick="addSrv()">Ajouter</button></div>`)}
function addSrv(){run(async()=>{await api('/api/serveur/ajouter',{nom:$('#s-n').value,adresse:$('#s-a').value});fermer();await charger()})}
function retSrv(i){run(async()=>{await api('/api/serveur/retirer',{adresse:S.serveurs[i].adresse});await charger()})}
function rejoindre(i){if(!S.profils.length)return toast('Crée d\'abord un profil.',true);jouer(+$('#sp-p').value,S.serveurs[i].adresse)}

/* ---------- Skins ---------- */
function pSkins(){const n=S.compte?S.compte.name:S.reglages.pseudo;
 $('#page').innerHTML=`<h1>Skins</h1><div class="row" style="align-items:flex-start;gap:30px;margin-top:20px"><div class="glass" style="width:250px;height:420px;display:grid;place-items:center"><img id="sk" src="https://mc-heads.net/body/${encodeURIComponent(n)}/260" style="max-height:380px" onerror="this.outerHTML='<span class=mut>Skin introuvable</span>'"></div>
 <div style="flex:1;min-width:280px"><label style="margin-top:0">Pseudo du joueur</label><div class="row"><input id="sk-n" value="${esc(n)}" style="flex:1" onkeydown="if(event.key=='Enter')voirSkin()"><button class="btn pri" onclick="voirSkin()">Voir</button></div>
 <div class="row" style="margin-top:14px"><button class="btn" onclick="url('https://namemc.com/profile/'+encodeURIComponent($('#sk-n').value))">NameMC</button><button class="btn" onclick="url('https://www.minecraft.net/fr-fr/msaprofile/mygames/editskin')">Changer mon skin</button></div>
 <div class="glass card" style="margin-top:22px"><b>Skin en mode hors-ligne</b><p class="mut" style="font-size:13px;margin:6px 0 12px">Sans compte Microsoft, Minecraft n'affiche pas ton skin. CustomSkinLoader le rend visible.</p>
 <div class="row"><select id="sk-p" style="width:220px">${S.profils.filter(x=>x.loader!='Vanilla').map(x=>`<option>${esc(x.nom)}</option>`).join('')||'<option value="">(aucun profil Fabric/Forge)</option>'}</select><button class="btn pri" onclick="skinMod()">Installer le mod</button></div></div></div></div>`}
function voirSkin(){const n=$('#sk-n').value.trim();if(!/^\w{3,16}$/.test(n))return toast('Pseudo invalide.',true);$('#sk').parentNode.innerHTML=`<img id="sk" src="https://mc-heads.net/body/${encodeURIComponent(n)}/260" style="max-height:380px" onerror="this.outerHTML='<span class=mut>Skin introuvable</span>'">`}
function skinMod(){const n=$('#sk-p').value;if(!n)return toast('Crée un profil Fabric ou Forge.',true);toast('Installation…');run(async()=>{await api('/api/skinmod',{nom:n});toast('Mod de skins installé ✔')})}

/* ---------- Actus / Perf / Journal / Réglages ---------- */
function pActus(){$('#page').innerHTML='<h1>Actualités Minecraft</h1><div class="grid" style="margin-top:20px" id="ac"><div class="mut">Chargement…</div></div>';
 api('/api/news').then(d=>{$('#ac').innerHTML=d.news.map(newsCard).join('')}).catch(e=>{$('#ac').innerHTML='<div class="mut">Impossible de charger les actualités : '+esc(e.message)+'</div>'})}
function pPerf(){api('/api/perf').then(d=>{const s=d.specs,c=x=>`<td>${vbadge(x)}</td>`;
 $('#page').innerHTML=`<h1>Performance de ton PC</h1><p class="mut" style="margin:6px 0 18px">Lohyx Hub compare ton matériel à ce que demande chaque version de Minecraft.</p>
 <div class="stats"><div class="glass stat"><b>${s.ram?s.ram+' Go':'…'}</b><span>Mémoire (RAM)</span></div><div class="glass stat"><b>${s.threads||'…'}</b><span>Threads processeur</span></div><div class="glass stat"><b style="font-size:16px">${esc((s.gpus||['…'])[0])}</b><span>Carte graphique</span></div></div>
 <h3>Légende</h3><div class="row" style="gap:22px">${[['vert','Parfait'],['jaune','Il faut se calmer'],['orange','Pas assez puissant'],['rouge','Quasi impossible']].map(([k,t])=>`<span class="pill"><i class="dot" style="background:${VC[k]}"></i>${t}</span>`).join('')}</div>
 <h3>Verdict par version</h3><div class="glass" style="padding:8px 14px"><table><tr><th>Version</th><th>Vanilla</th><th>Avec ~60 mods</th><th>Avec shaders</th></tr>${d.lignes.map(l=>`<tr><td><b>${l.version}</b></td>${c(l.vanilla)}${c(l.mods)}${c(l.shaders)}</tr>`).join('')}</table></div>`}).catch(e=>toast(e.message,true))}
function pJournal(){$('#page').innerHTML='<div class="row"><h1>Journal du jeu</h1><span class="sp"></span><span class="mut" style="font-size:12px">mis à jour toutes les 3 s</span></div><pre id="lg" style="margin-top:16px"></pre>';
 const f=()=>api('/api/log').then(d=>{const e=$('#lg');if(e){e.textContent=d.log;e.scrollTop=e.scrollHeight}});f();timerJ=setInterval(f,3000)}
function pReglages(){const r=S.reglages,cols=['#1bd96a','#7c5cff','#00b7ff','#ff4d8d','#ffb020','#ff5a36'];
 $('#page').innerHTML=`<h1>Réglages</h1><div class="grid" style="margin-top:20px"><div class="glass card"><h2>Joueur</h2><label>Pseudo (mode hors-ligne)</label><input id="r-p" value="${esc(r.pseudo)}" ${S.compte?'disabled':''}><label>RAM par défaut : <b id="r-v">${r.ram}</b> Go</label><input type="range" id="r-r" min="1" max="${Math.max(2,Math.min(32,Math.floor((S.specs.ram||8)-2)))}" value="${r.ram}" oninput="$('#r-v').textContent=this.value"><div style="margin-top:18px"><button class="btn pri" onclick="saveR()">Enregistrer</button></div></div>
 <div class="glass card"><h2>Couleur</h2><div class="row" style="margin-top:12px">${cols.map(c=>`<div class="sw ${c==r.accent?'on':''}" style="background:${c}" onclick="accent('${c}')"></div>`).join('')}</div></div>
 <div class="glass card"><h2>Compte Minecraft</h2>${S.compte?`<p class="mut" style="margin:6px 0 14px">Connecté : <b style="color:var(--txt)">${esc(S.compte.name)}</b></p><button class="btn red" onclick="login()">Se déconnecter</button>`
 :`<p class="mut" style="font-size:13px;margin:6px 0 14px;line-height:1.5">Une page officielle de Microsoft s'ouvre : connecte-toi avec le compte qui possède Minecraft Java, puis reviens ici.</p><button class="btn pri" style="width:100%;padding:13px" onclick="login()">🔐 Se connecter à votre compte Minecraft</button>
 ${S.login.msg?`<p style="font-size:13px;margin-top:12px;color:var(--orange)">${esc(S.login.msg)}</p>`:''}
 ${S.login_ok?'':'<p style="font-size:12.5px;margin-top:12px;color:var(--orange);line-height:1.5">⚠ Aucun Client ID Microsoft dans ce launcher : il faut le coller une fois dans la ligne CLIENT_ID de LohyxHub.pyw.</p>'}
 <details style="margin-top:12px"><summary class="mut" style="font-size:12px;cursor:pointer">Avancé : coller un Client ID</summary><input id="r-c" placeholder="Client ID Azure" style="margin-top:8px"></details>`}</div><div class="glass card"><h2>À propos</h2><p class="mut" style="margin:6px 0 14px">Lohyx Hub <b style="color:var(--txt)">version ${esc(S.version)}</b></p>${S.maj_actif?`<button class="btn" onclick="majVerifier()">Vérifier les mises à jour</button>`:'<p class="mut" style="font-size:12.5px;line-height:1.5">Mises à jour automatiques désactivées. Mets l\'adresse de ton site dans la ligne UPDATE_URL de LohyxHub.pyw.</p>'}</div></div>`}
function saveR(){run(async()=>{const b={ram:+$('#r-r').value};if(!S.compte)b.pseudo=$('#r-p').value;await api('/api/reglages',b);await charger();toast('Enregistré ✔')})}
function accent(c){run(async()=>{await api('/api/reglages',{accent:c});await charger()})}
function login(){if(S.compte&&!confirm('Te déconnecter de ton compte Minecraft ?'))return;run(async()=>{await api('/api/login',{client_id:$('#r-c')?$('#r-c').value:''});if(!S.compte)toast('Une page Microsoft s\'ouvre dans ton navigateur…');await charger()})}

/* ---------- Boucle de progression ---------- */
setInterval(async()=>{try{const p=await api('/api/progress');$('#fst').textContent=p.status;$('#fbar').style.width=p.pct+'%';$('#fpc').textContent=p.pct?p.pct+' %':'';
 if(p.error)toast(p.error,true);if(last.running&&!p.running)charger();last=p;if(S.login.busy||lb){const was=lb;await charger();lb=S.login.busy;if(was&&!lb)S.compte?toast('Connecté en tant que '+S.compte.name+' ✔'):S.login.msg&&toast(S.login.msg,true)}}catch(e){}},1000);
renderNav();charger();
</script></body></html>
"""

if __name__ == "__main__":
    main()
