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
import zipfile
from concurrent.futures import ThreadPoolExecutor
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
VERSION = "1.2.0"
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
DEFAUT = {"pseudo": "Joueur", "accent": "#7c6cff", "ram": 4, "resolution": "1920x1080",
          "plein_ecran": False, "fps": 0, "java": ""}
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
            "ram_systeme": SPECS.get("ram"),
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
    base = dossier_instance(trouver(b["nom"])["nom"])
    sous = b.get("sous", "")
    if sous in ("saves", "mods", "logs", "shaderpacks", "resourcepacks"):
        base = os.path.join(base, sous)
    ouvrir_chemin(base)
    return {"ok": True}


def api_racine(_):
    ouvrir_chemin(DOSSIER)
    return {"ok": True}


def api_sauvegarde(b):
    p = trouver(b["nom"])
    saves = os.path.join(dossier_instance(p["nom"]), "saves")
    if not os.path.isdir(saves) or not os.listdir(saves):
        raise RuntimeError("Aucun monde à sauvegarder dans ce profil.")
    dest = os.path.join(DOSSIER, "sauvegardes")
    os.makedirs(dest, exist_ok=True)
    base = os.path.join(dest, f"{p['nom']}_{time.strftime('%Y-%m-%d_%Hh%M')}")
    monde = os.path.basename(b.get("monde", ""))
    if monde:
        if not os.path.isdir(os.path.join(saves, monde)):
            raise RuntimeError("Monde introuvable.")
        archive = shutil.make_archive(base + "_" + re.sub(r"[^\w\-]", "", monde), "zip", root_dir=saves, base_dir=monde)
    else:
        archive = shutil.make_archive(base, "zip", saves)
    ouvrir_chemin(dest)
    return {"ok": True, "fichier": archive}


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


def api_profil_modifier(b):
    with VERROU:
        l = charger_profils()
        p = next((x for x in l if x["nom"] == b["nom"]), None)
        if not p:
            raise RuntimeError("Profil introuvable.")
        if "loader" in b:
            if b["loader"] not in ("Vanilla", "Fabric", "Forge"):
                raise RuntimeError("Type inconnu.")
            if b["loader"] != p["loader"]:
                p.pop("loader_version", None)
            p["loader"] = b["loader"]
        if "version" in b and b["version"] != p["version"]:
            if not re.fullmatch(r"[\w.\-]{1,30}", b["version"]):
                raise RuntimeError("Version invalide.")
            p["version"] = b["version"]
            p.pop("loader_version", None)
        if "ram" in b:
            p["ram"] = max(1, min(64, int(b["ram"])))
        ecrire_json(F_PROFILS, l)
    return {"ok": True}


def taille_dossier(d):
    total = 0
    for racine, _, fichiers in os.walk(d):
        for f in fichiers:
            try:
                total += os.path.getsize(os.path.join(racine, f))
            except OSError:
                pass
    return total


def api_mondes(_):
    out = []
    for p in charger_profils():
        saves = os.path.join(dossier_instance(p["nom"]), "saves")
        if not os.path.isdir(saves):
            continue
        for w in sorted(os.listdir(saves)):
            d = os.path.join(saves, w)
            if os.path.isdir(d):
                out.append({"profil": p["nom"], "nom": w, "taille": round(taille_dossier(d) / 2 ** 20, 1),
                            "modifie": time.strftime("%d/%m/%Y", time.localtime(os.path.getmtime(d)))})
    return {"mondes": out}


def api_reparer(b):
    p = trouver(b["nom"])
    v = p["version"]
    base = os.path.join(DOSSIER, "versions")
    retire = []
    if os.path.isdir(base):
        for d in os.listdir(base):
            if d == v or d.endswith("-" + v) or d.startswith(v + "-"):
                shutil.rmtree(os.path.join(base, d), ignore_errors=True)
                retire.append(d)
    return {"ok": True, "retire": retire}


def regler_fps(jeu, fps):
    chemin = os.path.join(jeu, "options.txt")
    val = 260 if not fps else fps  # 260 = illimité dans Minecraft
    try:
        lignes = open(chemin, encoding="utf-8").read().splitlines() if os.path.exists(chemin) else []
        for i, l in enumerate(lignes):
            if l.startswith("maxFps:"):
                lignes[i] = f"maxFps:{val}"
                break
        else:
            lignes.append(f"maxFps:{val}")
        with open(chemin, "w", encoding="utf-8") as f:
            f.write("\n".join(lignes) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- modpacks (.mrpack)
def chemin_sur(base, rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise ValueError("chemin interdit")
    base_abs = os.path.abspath(base)
    dest = os.path.abspath(os.path.join(base_abs, rel))
    if os.path.commonpath([base_abs, dest]) != base_abs:
        raise ValueError("chemin interdit")
    return dest


def nom_profil_libre(titre):
    base = re.sub(r"[^\w \-]", "", titre).strip()[:26] or "Modpack"
    noms = {p["nom"].lower() for p in charger_profils()}
    nom, i = base, 2
    while nom.lower() in noms:
        nom, i = f"{base} {i}", i + 1
    return nom


def api_modpacks(a):
    q = a.get("q", "").strip()
    limite = max(1, min(30, int(a.get("limite", 20))))
    d = api_modrinth("/search", query=q, facets=json.dumps([["project_type:modpack"]]), limit=limite,
                     index="relevance" if q else "downloads")
    deja = {p.get("modpack") for p in charger_profils() if p.get("modpack")}
    out = []
    for h in d["hits"]:
        cats = [c.lower() for c in h.get("categories", [])]
        out.append({"id": h["project_id"], "titre": h["title"], "desc": h["description"], "dl": h["downloads"],
                    "icone": h.get("icon_url") or "", "installe": h["project_id"] in deja,
                    "compatible": "fabric" in cats or "forge" in cats,
                    "loaders": [c for c in cats if c in ("fabric", "forge", "neoforge", "quilt")]})
    return {"modpacks": out}


def installer_mrpack(pid):
    versions = api_modrinth(f"/project/{pid}/version", loaders=json.dumps(["fabric", "forge"]))
    if not versions:
        raise RuntimeError("Ce modpack n'a pas de version Fabric ou Forge (NeoForge et Quilt ne sont pas encore gérés).")
    v = versions[0]
    fichier = next((f for f in v["files"] if f.get("primary")), v["files"][0])
    if not fichier["filename"].endswith(".mrpack"):
        raise RuntimeError("Format de modpack non reconnu.")
    statut("Téléchargement du modpack...", 5)
    tmp = os.path.join(DOSSIER, "tmp")
    os.makedirs(tmp, exist_ok=True)
    chemin = os.path.join(tmp, uuid.uuid4().hex + ".mrpack")
    jeu = None
    try:
        telecharger(fichier["url"], chemin)
        with zipfile.ZipFile(chemin) as z:
            index = json.loads(z.read("modrinth.index.json"))
            deps = index.get("dependencies", {})
            mc = deps.get("minecraft")
            if not mc:
                raise RuntimeError("Modpack invalide (version de Minecraft absente).")
            if "fabric-loader" in deps:
                loader, lv = "Fabric", deps["fabric-loader"]
            elif "forge" in deps:
                loader, lv = "Forge", deps["forge"]
            else:
                raise RuntimeError("Ce modpack utilise NeoForge ou Quilt, pas encore gérés par Lohyx Hub.")
            nom = nom_profil_libre(index.get("name") or "Modpack")
            jeu = dossier_instance(nom)
            os.makedirs(jeu, exist_ok=True)
            fichiers = [f for f in index.get("files", []) if (f.get("env") or {}).get("client") != "unsupported"]
            total, fait = max(len(fichiers), 1), [0]

            def une(f):
                dest = chemin_sur(jeu, f["path"])
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                url = f["downloads"][0]
                if not url_sure(url):
                    raise RuntimeError("Adresse de téléchargement non sûre dans le modpack.")
                telecharger(url, dest)
                sha1 = (f.get("hashes") or {}).get("sha1")
                if sha1 and hashlib.sha1(open(dest, "rb").read()).hexdigest() != sha1.lower():
                    os.remove(dest)
                    raise RuntimeError(f"Fichier corrompu : {os.path.basename(dest)}")
                fait[0] += 1
                statut(f"Modpack : {fait[0]}/{total} fichiers", 10 + int(80 * fait[0] / total))
            with ThreadPoolExecutor(6) as ex:
                list(ex.map(une, fichiers))
            for nm in z.namelist():
                for pref in ("overrides/", "client-overrides/"):
                    if nm.startswith(pref) and not nm.endswith("/"):
                        dest = chemin_sur(jeu, nm[len(pref):])
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        with z.open(nm) as src, open(dest, "wb") as out:
                            shutil.copyfileobj(src, out)
        for sous in ("mods", "shaderpacks", "resourcepacks"):
            os.makedirs(os.path.join(jeu, sous), exist_ok=True)
        with VERROU:
            l = charger_profils()
            l.append({"nom": nom, "version": mc, "loader": loader, "loader_version": lv, "ram": 6, "temps": 0,
                      "modpack": pid})
            ecrire_json(F_PROFILS, l)
        return nom
    except Exception:
        if jeu:
            shutil.rmtree(jeu, ignore_errors=True)
        raise
    finally:
        try:
            os.remove(chemin)
        except OSError:
            pass


def _tache_modpack(pid):
    try:
        nom = installer_mrpack(pid)
        statut(f"Modpack installé ! Profil « {nom} » créé.", 100)
    except Exception as e:
        statut("Erreur")
        P["error"] = str(e)
    finally:
        P["busy"] = False


def api_modpack_installer(b):
    if P["busy"]:
        raise RuntimeError("Une opération est déjà en cours, patiente un instant.")
    P.update(busy=True, pct=0, error="")
    threading.Thread(target=_tache_modpack, args=(b["id"],), daemon=True).start()
    return {"ok": True}


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
    man = lire_manifest(p).get(genre, {})
    dossier_g = os.path.join(dossier_instance(p["nom"]), DOSSIERS_MR[genre][1])

    def installe(pid):
        return pid in man and os.path.exists(os.path.join(dossier_g, man[pid]["fichier"]))
    return {"resultats": [{"id": h["project_id"], "titre": h["title"], "desc": h["description"],
                           "dl": h["downloads"], "icone": h.get("icon_url") or "",
                           "auteur": h.get("author", ""), "installe": installe(h["project_id"])}
                          for h in d["hits"]]}


def f_manifest(p):
    return os.path.join(dossier_instance(p["nom"]), "lohyx_installes.json")


def lire_manifest(p):
    return lire_json(f_manifest(p), {})


def noter_installe(p, genre, pid, titre, fichier):
    m = lire_manifest(p)
    m.setdefault(genre, {})[pid] = {"titre": titre, "fichier": fichier}
    ecrire_json(f_manifest(p), m)


def oublier_installe(p, genre, fichier):
    m = lire_manifest(p)
    d = m.get(genre, {})
    for k in [k for k, v in d.items() if v.get("fichier") == fichier]:
        del d[k]
    ecrire_json(f_manifest(p), m)


def installer_projet(pid, p, genre, vus, titre=None):
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
    nom_projet = titre
    if not nom_projet:
        try:
            nom_projet = api_modrinth(f"/project/{v.get('project_id', pid)}")["title"]
        except Exception:
            nom_projet = nom_fichier
    noter_installe(p, genre, v.get("project_id", pid), nom_projet, nom_fichier)
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
        n = installer_projet(b["id"], trouver(b["nom"]), b.get("genre", "mods"), set(), b.get("titre"))
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
    genre = a.get("genre", "mods")
    titres = {v["fichier"]: v["titre"] for v in lire_manifest(p).get(genre, {}).values()}
    return {"fichiers": lister(p, genre), "titres": titres}


def api_retirer(b):
    p = trouver(b["nom"])
    nom_f = os.path.basename(b["fichier"])
    chemin = os.path.join(dossier_instance(p["nom"]), DOSSIERS_MR[b["genre"]][1], nom_f)
    if os.path.isfile(chemin):
        os.remove(chemin)
    oublier_installe(p, b["genre"], nom_f)
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
    if "resolution" in b:
        if not re.fullmatch(r"\d{3,4}x\d{3,4}", b["resolution"]):
            raise RuntimeError("Résolution invalide.")
        r["resolution"] = b["resolution"]
    if "plein_ecran" in b:
        r["plein_ecran"] = bool(b["plein_ecran"])
    if "fps" in b:
        if int(b["fps"]) not in (0, 30, 60, 120, 144, 240):
            raise RuntimeError("Valeur de FPS invalide.")
        r["fps"] = int(b["fps"])
    if "java" in b:
        j = b["java"].strip()
        if j and not (os.path.isfile(j) and os.path.basename(j).lower() in ("java.exe", "javaw.exe", "java")):
            raise RuntimeError("Ce n'est pas un fichier java.exe valide.")
        r["java"] = j
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
    return {"status": P["status"], "pct": P["pct"], "running": P["running"], "busy": P["busy"], "error": err}


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
                   "customResolution": True, "resolutionWidth": r["resolution"].split("x")[0],
                   "resolutionHeight": r["resolution"].split("x")[1]}
        if COMPTE:
            statut("Vérification du compte...")
            c = rafraichir_compte()
            options.update({"username": c["name"], "uuid": c["id"], "token": c["access_token"]})
        if cible:
            if version_tuple(version) >= (1, 20):
                options["quickPlayMultiplayer"] = f"{cible[0]}:{cible[1]}"
            else:
                options["server"], options["port"] = cible[0], str(cible[1])

        regler_fps(jeu, r["fps"])
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
        if r.get("java") and os.path.isfile(r["java"]):
            java_exe = options["executablePath"] = r["java"]
        id_lancement = version
        lv = p.get("loader_version")
        if loader == "Fabric":
            if not mll.fabric.is_minecraft_version_supported(version):
                raise RuntimeError(f"Fabric ne gère pas la version {version}.")
            statut("Installation de Fabric...")
            appeler(mll.fabric.install_fabric, version, DOSSIER, callback=callback, java=java_exe,
                    **({"loader_version": lv} if lv else {}))
            id_lancement = f"fabric-loader-{lv or mll.fabric.get_latest_loader_version()}-{version}"
        elif loader == "Forge":
            fv = f"{version}-{lv}" if lv else mll.forge.find_forge_version(version)
            if not fv:
                raise RuntimeError(f"Forge n'existe pas pour la version {version}. Essaie 1.20.1.")
            if not mll.forge.supports_automatic_install(fv):
                raise RuntimeError("Cette version de Forge ne s'installe pas automatiquement.")
            statut("Installation de Forge (peut être long)...")
            appeler(mll.forge.install_forge_version, fv, DOSSIER, callback=callback, java=java_exe)
            id_lancement = mll.forge.forge_to_installed_version(fv)

        commande = mll.command.get_minecraft_command(id_lancement, DOSSIER, options)
        if r.get("plein_ecran"):
            commande.append("--fullscreen")
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
    ("GET", "/api/modpacks"): api_modpacks, ("POST", "/api/modpack/installer"): api_modpack_installer,
    ("POST", "/api/profil/modifier"): api_profil_modifier, ("GET", "/api/mondes"): api_mondes,
    ("POST", "/api/reparer"): api_reparer, ("POST", "/api/ouvrir_racine"): api_racine,
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
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9Ii01NiAtNjQgMTEyIDExNCI+PHJlY3QgeD0iLTU2IiB5PSItNjQiIHdpZHRoPSIxMTIiIGhlaWdodD0iMTE0IiByeD0iMjQiIGZpbGw9IiMwYjBkMTIiLz48cG9seWdvbiBwb2ludHM9Ii0yNi4wLC0xNS4wIDAuMCwwLjAgMC4wLDMwLjAgLTI2LjAsMTUuMCIgZmlsbD0iIzdjNWNmZiIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLDAuMCAyNi4wLC0xNS4wIDI2LjAsMTUuMCAwLjAsMzAuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLC0zMC4wIDI2LjAsLTE1LjAgMC4wLDAuMCAtMjYuMCwtMTUuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iLTUyLjAsMC4wIC0yNi4wLDE1LjAgLTI2LjAsNDUuMCAtNTIuMCwzMC4wIiBmaWxsPSIjN2M1Y2ZmIi8+PHBvbHlnb24gcG9pbnRzPSItMjYuMCwxNS4wIDAuMCwwLjAgMC4wLDMwLjAgLTI2LjAsNDUuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iLTI2LjAsLTE1LjAgMC4wLDAuMCAtMjYuMCwxNS4wIC01Mi4wLDAuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLDAuMCAyNi4wLDE1LjAgMjYuMCw0NS4wIDAuMCwzMC4wIiBmaWxsPSIjN2M1Y2ZmIi8+PHBvbHlnb24gcG9pbnRzPSIyNi4wLDE1LjAgNTIuMCwwLjAgNTIuMCwzMC4wIDI2LjAsNDUuMCIgZmlsbD0iIzNiMmFhOCIvPjxwb2x5Z29uIHBvaW50cz0iMjYuMCwtMTUuMCA1Mi4wLDAuMCAyNi4wLDE1LjAgMC4wLDAuMCIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjxwb2x5Z29uIHBvaW50cz0iLTIwLjMsLTQ3LjcgMC4wLC0zNi4wIDAuMCwtMTIuNiAtMjAuMywtMjQuMyIgZmlsbD0iIzdjNWNmZiIvPjxwb2x5Z29uIHBvaW50cz0iMC4wLC0zNi4wIDIwLjMsLTQ3LjcgMjAuMywtMjQuMyAwLjAsLTEyLjYiIGZpbGw9IiMzYjJhYTgiLz48cG9seWdvbiBwb2ludHM9IjAuMCwtNTkuNCAyMC4zLC00Ny43IDAuMCwtMzYuMCAtMjAuMywtNDcuNyIgZmlsbD0iIzRiZTU4YSIgc3Ryb2tlPSJyZ2JhKDI1NSwyNTUsMjU1LC4zNSkiIHN0cm9rZS13aWR0aD0iMSIvPjwvc3ZnPg==">
<style>
:root{--a:#7c6cff;--bg:#0a0d19;--side:#0c1022;--panel:#11162d;--panel2:#171d3b;--line:#232a52;--txt:#eef1ff;--mut:#8f98c0;--vert:#22c55e;--jaune:#facc15;--orange:#fb923c;--rouge:#ef4444}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;color:var(--txt);font-family:"Segoe UI Variable","Segoe UI",system-ui,sans-serif;overflow:hidden;background:radial-gradient(1100px 520px at 62% -12%,rgba(124,108,255,.16),transparent),var(--bg)}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-thumb{background:rgba(255,255,255,.13);border-radius:8px}
button,select,input{font-family:inherit}
#app{display:flex;height:100%}
aside{width:190px;flex:none;padding:14px 10px 12px;display:flex;flex-direction:column;background:var(--side);border-right:1px solid var(--line)}
.brand{display:flex;align-items:center;gap:9px;padding:2px 6px 14px}.brand b{display:block;font-size:15.5px;line-height:1.15}.brand small{display:block;font-size:10.5px;color:var(--mut);margin-top:1px}
nav{flex:1;overflow:auto;display:flex;flex-direction:column;gap:2px;padding-right:2px}
nav button{display:flex;align-items:center;gap:11px;padding:9px 11px;border:1px solid transparent;border-radius:9px;background:transparent;color:#a9b2da;font-size:13.5px;font-weight:600;cursor:pointer;text-align:left;transition:.15s}
nav button:hover{background:rgba(255,255,255,.05);color:#fff}
nav button.on{background:#1b2150;border-color:#2c3578;color:#fff;box-shadow:0 0 18px rgba(124,108,255,.18)}
.ic{width:18px;height:18px;flex:none}
.acct{padding:10px 4px 0;border-top:1px solid var(--line);margin-top:8px}.acct h6{font-size:11px;color:var(--mut);font-weight:600;margin:0 4px 8px;display:flex;gap:6px;align-items:center}
.who{display:flex;align-items:center;gap:9px;padding:0 4px}.who img{width:34px;height:34px;border-radius:50%;background:#1d2350;image-rendering:pixelated}.who b{display:block;font-size:13px}.who small{font-size:11px;color:var(--mut)}
.who small i{display:inline-block;width:7px;height:7px;border-radius:50%;background:#22c55e;margin-right:5px}.who small i.off{background:#6b7399}
.acct .btn{width:100%;margin-top:10px;padding:8px;font-size:12.5px;background:#2a2f78;border-color:#3b43a0}
.ver{text-align:center;font-size:11px;color:var(--mut);margin-top:10px}.slogan{text-align:center;font-size:10.5px;color:#6f78a3;font-style:italic;margin-top:8px;line-height:1.35}
main{flex:1;min-width:0;display:flex;flex-direction:column;position:relative}
#maj{display:none;align-items:center;gap:12px;padding:10px 20px;border-bottom:1px solid var(--line);background:linear-gradient(90deg,rgba(124,108,255,.25),rgba(255,255,255,.03));font-size:13.5px}
#page{flex:1;overflow:auto}
#prog{display:none;position:absolute;left:20px;right:20px;bottom:14px;align-items:center;gap:14px;padding:10px 16px;border-radius:12px;background:#171c3d;border:1px solid #2c3578;box-shadow:0 8px 30px rgba(0,0,0,.5);font-size:13px;z-index:30}
.pbw{flex:1;height:7px;border-radius:7px;background:rgba(255,255,255,.1);overflow:hidden}#fbar{height:100%;width:0;background:linear-gradient(90deg,#7c6cff,#4ade80);transition:width .4s}
.mut{color:var(--mut)}.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.sp{flex:1}.nw{flex-wrap:nowrap!important}
.btn{white-space:nowrap;border:1px solid var(--line);background:rgba(255,255,255,.06);color:var(--txt);padding:9px 15px;border-radius:10px;font-size:13px;font-weight:700;cursor:pointer;transition:.15s}
.btn:hover{background:rgba(255,255,255,.12)}.btn.pri{background:var(--a);border-color:transparent;color:#fff}.btn.pri:hover{filter:brightness(1.12)}
.btn.red{background:rgba(239,68,68,.15);color:#ff9a9a}.btn.ok{background:rgba(34,197,94,.16);border-color:rgba(34,197,94,.45);color:#6ee79a;cursor:default}.btn.ic2{padding:8px 11px}
input,select{padding:9px 11px;border-radius:9px;border:1px solid var(--line);background:#0e1330;color:var(--txt);font-size:13px;outline:none}
input:focus,select:focus{border-color:var(--a)}select option{background:#12172f}input.full,select.full{width:100%}input[type=range]{padding:0;accent-color:var(--a)}
label.l{display:block;margin:14px 0 6px;font-size:11.5px;color:var(--mut);letter-spacing:1px;text-transform:uppercase}
/* ---------- accueil ---------- */
.home{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:14px;padding:12px 16px 20px}
.hero{position:relative;height:250px;border-radius:14px;overflow:hidden;border:1px solid var(--line)}
.hero .art{position:absolute;inset:0}.hero .art svg{width:100%;height:100%;display:block}
.hero:after{content:"";position:absolute;inset:0;background:linear-gradient(180deg,rgba(8,10,25,.12),rgba(8,10,25,0) 35%,rgba(8,10,25,.7))}
.hero-c{position:absolute;z-index:2;left:0;right:0;top:14px;text-align:center}
.logotype{display:inline-flex;align-items:center;gap:14px;font-family:Impact,"Arial Black",system-ui,sans-serif;font-weight:900;font-size:46px;letter-spacing:5px;text-transform:uppercase;line-height:1;background:linear-gradient(#f4f6fb,#a7afc4);-webkit-background-clip:text;background-clip:text;color:transparent;filter:drop-shadow(0 3px 0 #3a4160) drop-shadow(0 6px 0 #232844) drop-shadow(0 12px 14px rgba(0,0,0,.6))}
.tag{margin:8px 0 11px;font-size:14px;color:#fff;text-shadow:0 2px 8px rgba(0,0,0,.7)}
.play{border:0;border-radius:11px;padding:11px 50px;font-size:19px;font-weight:800;color:#04140a;cursor:pointer;letter-spacing:.5px;transition:.15s;display:inline-flex;align-items:center;gap:10px}
.play:hover{transform:translateY(-2px) scale(1.03)}.play:disabled{opacity:.7;cursor:default;transform:none}
.play.v-vert{background:linear-gradient(#45e17f,#22b45a);box-shadow:0 8px 28px rgba(34,197,94,.5)}.play.v-jaune{background:linear-gradient(#ffe45c,#e0b800);box-shadow:0 8px 28px rgba(250,204,21,.45)}
.play.v-orange{background:linear-gradient(#ffac6b,#e8741f);box-shadow:0 8px 28px rgba(251,146,60,.45)}.play.v-rouge{background:linear-gradient(#ff6b6b,#d92d2d);color:#fff;box-shadow:0 8px 28px rgba(239,68,68,.5)}
.play.sm{padding:8px 18px;font-size:13px;border-radius:9px;box-shadow:none!important}
.selbar{position:absolute;z-index:2;left:50%;bottom:12px;transform:translateX(-50%);display:flex;align-items:center;gap:0;padding:7px 8px;border-radius:12px;background:rgba(10,13,32,.72);backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.1);font-size:12px;white-space:nowrap}
.selbar label{display:flex;align-items:center;gap:7px;padding:0 12px;color:#cdd3f5}.selbar i{width:1px;height:22px;background:rgba(255,255,255,.14)}
.selbar select{background:transparent;border:0;color:#fff;font-weight:600;font-size:12.5px;padding:3px 2px;cursor:pointer}
.sec{margin-top:11px}.sec>.hd{display:flex;align-items:center;gap:8px;margin-bottom:9px;font-weight:700;font-size:14.5px}.sec>.hd a{margin-left:auto;font-size:12px;font-weight:500;color:#aab2e6;cursor:pointer}.sec>.hd a:hover{color:#fff}
.sec>.hd em{font-style:normal;color:#ff8a4c}
.prow{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:9px}
.pc{position:relative;height:100px;padding-bottom:16px!important;border-radius:11px;background:var(--panel);border:1px solid var(--line);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;cursor:pointer;transition:.15s;text-align:center;padding:6px}
.pc:hover{border-color:#3a4390}.pc b{font-size:12.5px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pc small{font-size:10.5px;color:var(--mut)}
.pc.on{border-color:#7c6cff;box-shadow:0 0 0 1px #7c6cff,0 0 22px rgba(124,108,255,.35);background:#161c42}
.pc.new{border-style:dashed;color:#b9c0ee;font-size:12px}.pc.new span{font-size:22px;line-height:1}
.pc .pl{position:absolute;left:50%;bottom:2px;transform:translateX(-50%);font-size:10px;color:#4ade80;padding:1px 10px;cursor:pointer}
.pc .dv{position:absolute;top:7px;right:7px;width:8px;height:8px;border-radius:50%}
.mrow{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}
.mp{border-radius:11px;background:var(--panel);border:1px solid var(--line);overflow:hidden;transition:.15s}.mp:hover{border-color:#3a4390;transform:translateY(-2px)}
.mp .im{height:72px;background:linear-gradient(135deg,#2a2f78,#12172f);display:grid;place-items:center;overflow:hidden}.mp .im img{width:100%;height:100%;object-fit:cover}
.mp .bd{padding:7px 9px 8px}.mp .r2{display:flex;align-items:center;margin-top:3px}.mp b{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.mp small{font-size:10.5px;color:var(--mut)}
.dlb{margin-left:auto;flex:none;width:28px;height:28px;border-radius:8px;border:1px solid var(--line);background:rgba(255,255,255,.07);color:#cfd5ff;cursor:pointer;font-size:14px}.dlb:hover{background:var(--a);color:#fff}.dlb.ok{background:rgba(34,197,94,.18);border-color:rgba(34,197,94,.5);color:#6ee79a;cursor:default}
.nrow{display:grid;grid-template-columns:1.15fr 1fr;gap:12px}
.nbig{display:flex;gap:12px;padding:12px;border-radius:12px;background:var(--panel);border:1px solid var(--line)}.nbig img{width:118px;height:92px;object-fit:cover;border-radius:9px;background:#1d2350;flex:none}
.nbig h4{font-size:14px;margin-bottom:5px}.nbig p{font-size:11.5px;color:var(--mut);line-height:1.45}.nbig .ft{display:flex;align-items:center;margin-top:8px;font-size:11px;color:var(--mut)}.nbig .btn{margin-left:auto;padding:6px 12px;font-size:11.5px}
.nlist{display:flex;flex-direction:column;gap:7px}.ni{display:flex;gap:10px;align-items:center;padding:7px 9px;border-radius:10px;background:var(--panel);border:1px solid var(--line);cursor:pointer}.ni:hover{border-color:#3a4390}
.ni img{width:52px;height:38px;border-radius:7px;object-fit:cover;background:#1d2350;flex:none}.ni b{display:block;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ni small{font-size:10.5px;color:var(--mut)}
.rc{border-radius:12px;background:var(--panel);border:1px solid var(--line);padding:10px 13px;margin-bottom:10px}
.rc>.hd,.rc summary{display:flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px;cursor:pointer;list-style:none}.rc summary::-webkit-details-marker{display:none}.rc summary:after{content:"⌄";margin-left:auto;color:var(--mut)}.rc details[open] summary:after{content:"⌃"}
.rc .hd .gear{margin-left:auto;cursor:pointer;color:var(--mut)}
.cur{display:flex;gap:11px;align-items:center;margin:9px 0}.cur .cv{width:54px;height:54px;border-radius:10px;background:#1d2350;display:grid;place-items:center;flex:none}
.cur b{display:block;font-size:14px}.st{font-size:12px;display:flex;align-items:center;gap:6px;margin-top:3px}.dot{display:inline-block;width:8px;height:8px;border-radius:50%}
.mini{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:8px 0 10px}.mini div{padding:8px 4px;text-align:center;border-right:1px solid var(--line)}.mini div:last-child{border:0}.mini small{display:block;font-size:10.5px;color:var(--mut)}.mini b{font-size:13px}
.qs{display:grid;grid-template-columns:auto 1fr;gap:8px 8px;align-items:center;margin-top:9px;font-size:12.5px}.qs span{display:flex;gap:8px;align-items:center;color:#cdd3f5}.qs select{width:100%;padding:7px 9px}
.sw{position:relative;display:inline-block;width:42px;height:24px}.sw input{opacity:0;width:0;height:0}.sw i{position:absolute;inset:0;border-radius:24px;background:#2a3064;transition:.2s;cursor:pointer}.sw i:before{content:"";position:absolute;left:3px;top:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.2s}.sw input:checked+i{background:#4f5bff}.sw input:checked+i:before{transform:translateX(18px)}
.sc{margin-top:8px}.sc a{display:flex;align-items:center;gap:11px;padding:7px 2px;font-size:12.5px;color:#cdd3f5;cursor:pointer;border-radius:8px}.sc a:hover{color:#fff;background:rgba(255,255,255,.04)}
.srvbox{display:flex;align-items:center;gap:10px;font-size:13px}.srvbox b{display:block;font-size:12px;color:var(--mut);font-weight:500}
/* ---------- autres pages ---------- */
.pg{padding:22px 26px 40px}.pg h1{font-size:25px;font-weight:800}.pg h2{font-size:17px;font-weight:800;margin-bottom:6px}.pg h3{margin:24px 0 10px;font-size:12px;letter-spacing:2px;color:var(--mut);text-transform:uppercase}
.glass{background:var(--panel);border:1px solid var(--line);border-radius:14px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}.card{padding:16px}
.bar{height:8px;border-radius:8px;background:rgba(255,255,255,.08);overflow:hidden;margin:5px 0 12px}.bar i{display:block;height:100%;border-radius:8px}.bl{display:flex;justify-content:space-between;font-size:12.5px}.bl b{white-space:nowrap}.bl span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-left:12px;color:var(--mut)}
.verdict{margin-top:14px;padding:11px 14px;border-radius:12px;font-size:13px;border:1px solid;line-height:1.45}
.verdict.v-vert{border-color:var(--vert);background:rgba(34,197,94,.1)}.verdict.v-jaune{border-color:var(--jaune);background:rgba(250,204,21,.09)}.verdict.v-orange{border-color:var(--orange);background:rgba(251,146,60,.1)}.verdict.v-rouge{border-color:var(--rouge);background:rgba(239,68,68,.1)}
.pill{display:inline-flex;align-items:center;font-size:12.5px;font-weight:700}.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-top:14px}.stat{padding:16px}.stat b{display:block;font-size:22px;font-weight:800;color:var(--a)}.stat span{font-size:11.5px;color:var(--mut);text-transform:uppercase;letter-spacing:1.4px}
.tabs{display:flex;gap:6px;margin:14px 0}.tabs button{padding:8px 16px;border-radius:30px;border:1px solid var(--line);background:transparent;color:var(--mut);font-weight:700;cursor:pointer}.tabs button.on{background:var(--a);color:#fff;border-color:transparent}
.mod{display:flex;gap:13px;padding:13px}.mod img{width:54px;height:54px;border-radius:12px;background:#1d2350;object-fit:cover;flex:none}.mod h4{font-size:14.5px}.mod p{font-size:12.3px;color:var(--mut);margin:3px 0 9px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.news img.cv{width:100%;height:140px;object-fit:cover;border-radius:10px;margin-bottom:10px;background:#1d2350}.tag2{font-size:11px;padding:3px 9px;border-radius:20px;background:rgba(255,255,255,.1);color:var(--mut);font-weight:700}
table{width:100%;border-collapse:collapse}th,td{padding:12px 13px;text-align:left;border-bottom:1px solid var(--line);font-size:13.5px}th{color:var(--mut);font-size:11.5px;letter-spacing:1.4px;text-transform:uppercase}
.modal{position:fixed;inset:0;background:rgba(2,4,14,.7);backdrop-filter:blur(6px);display:none;place-items:center;z-index:60}.modal.on{display:grid}.box{width:440px;max-width:92vw;padding:26px;background:#11162d}
#toasts{position:fixed;right:20px;bottom:70px;display:flex;flex-direction:column;gap:8px;z-index:70}.toast{padding:12px 16px;border-radius:12px;background:#171c3d;border:1px solid var(--a);max-width:370px;font-size:13px;animation:in .3s}.toast.bad{border-color:var(--rouge)}@keyframes in{from{transform:translateX(40px);opacity:0}}
pre{padding:15px;border-radius:12px;background:rgba(0,0,0,.4);font-size:12px;line-height:1.5;white-space:pre-wrap;max-height:62vh;overflow:auto;color:#b7c2e6}
.seg{display:flex;gap:6px}.seg button{flex:1;padding:9px;border-radius:10px;border:1px solid var(--line);background:rgba(255,255,255,.05);color:var(--txt);font-weight:700;cursor:pointer}.seg button.on{background:var(--a);border-color:transparent;color:#fff}
.sws{width:32px;height:32px;border-radius:50%;cursor:pointer;border:3px solid transparent}.sws.on{border-color:#fff}
@media (max-width:1120px){.home{grid-template-columns:1fr}.prow{grid-template-columns:repeat(3,1fr)}.mrow{grid-template-columns:repeat(3,1fr)}.nrow{grid-template-columns:1fr}}
</style></head>
<body>
<div id="app">
<aside><div class="brand" id="brand"></div><nav id="nav"></nav>
<div class="acct"><h6>👤 Compte</h6><div class="who" id="me"></div><div id="me2"></div><div class="ver" id="ver"></div><div class="slogan">“Plus qu'un launcher…<br>une expérience.”</div></div></aside>
<main><div id="maj"></div><div id="page"></div>
<div id="prog"><span id="fst"></span><div class="pbw"><div id="fbar"></div></div><span id="fpc"></span></div></main>
</div>
<div class="modal" id="modal" onclick="if(event.target===this)fermer()"><div class="glass box" id="mbox"></div></div>
<div id="toasts"></div>
<script>
const HERO='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 340" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="hs" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#150f3d"/><stop offset=".42" stop-color="#4c2a86"/><stop offset=".7" stop-color="#d4507a"/><stop offset="1" stop-color="#ffb066"/></linearGradient><linearGradient id="hw" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#f08a70"/><stop offset="1" stop-color="#3b2a78"/></linearGradient><radialGradient id="hg"><stop offset="0" stop-color="#fff0c8" stop-opacity=".95"/><stop offset="1" stop-color="#ff9a5c" stop-opacity="0"/></radialGradient></defs><rect width="1000" height="340" fill="url(#hs)"/><rect x="168" y="104" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="428" y="72" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="860" y="52" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="824" y="128" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="516" y="60" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="12" y="92" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="436" y="16" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="812" y="56" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="708" y="8" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="756" y="104" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="452" y="8" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="552" y="124" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="116" y="92" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="156" y="20" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="828" y="4" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="164" y="84" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="496" y="36" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="680" y="8" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="884" y="60" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="796" y="48" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="688" y="16" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="572" y="120" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="844" y="96" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="348" y="36" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="416" y="72" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="976" y="112" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="392" y="80" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="392" y="68" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="852" y="20" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="732" y="124" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="500" y="16" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="612" y="56" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="620" y="80" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="636" y="28" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="684" y="40" width="3" height="3" fill="#fff" opacity="0.8"/><rect x="356" y="84" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="780" y="76" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="104" y="40" width="3" height="3" fill="#fff" opacity="0.3"/><rect x="944" y="44" width="3" height="3" fill="#fff" opacity="0.5"/><rect x="380" y="40" width="3" height="3" fill="#fff" opacity="0.8"/><circle cx="540" cy="215" r="170" fill="url(#hg)"/><circle cx="540" cy="215" r="54" fill="#fff1cb"/><rect x="120" y="70" width="90" height="14" fill="#ffd0e0" opacity=".30"/><rect x="90" y="84" width="150" height="14" fill="#ffd0e0" opacity=".30"/><rect x="110" y="98" width="110" height="14" fill="#ffd0e0" opacity=".30"/><rect x="700" y="52" width="90" height="14" fill="#ffd0e0" opacity=".30"/><rect x="670" y="66" width="150" height="14" fill="#ffd0e0" opacity=".30"/><rect x="690" y="80" width="110" height="14" fill="#ffd0e0" opacity=".30"/><rect x="880" y="108" width="90" height="14" fill="#ffd0e0" opacity=".30"/><rect x="850" y="122" width="150" height="14" fill="#ffd0e0" opacity=".30"/><rect x="870" y="136" width="110" height="14" fill="#ffd0e0" opacity=".30"/><rect x="330" y="96" width="90" height="14" fill="#ffd0e0" opacity=".30"/><rect x="300" y="110" width="150" height="14" fill="#ffd0e0" opacity=".30"/><rect x="320" y="124" width="110" height="14" fill="#ffd0e0" opacity=".30"/><rect x="0" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="20" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="40" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="60" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="80" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="100" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="120" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="140" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="160" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="180" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="200" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="220" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="240" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="260" y="200" width="20" height="140" fill="#35205f" opacity=".92"/><rect x="280" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="300" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="320" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="340" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="360" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="380" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="400" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="420" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="440" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="460" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="480" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="500" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="520" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="540" y="200" width="20" height="140" fill="#35205f" opacity=".92"/><rect x="560" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="580" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="600" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="620" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="640" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="660" y="160" width="20" height="180" fill="#35205f" opacity=".92"/><rect x="680" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="700" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="720" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="740" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="760" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="780" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="800" y="180" width="20" height="160" fill="#35205f" opacity=".92"/><rect x="820" y="200" width="20" height="140" fill="#35205f" opacity=".92"/><rect x="840" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="860" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="880" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="900" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="920" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="940" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="960" y="240" width="20" height="100" fill="#35205f" opacity=".92"/><rect x="980" y="220" width="20" height="120" fill="#35205f" opacity=".92"/><rect x="0" y="260" width="20" height="80" fill="#1f3a63"/><rect x="20" y="260" width="20" height="80" fill="#1f3a63"/><rect x="40" y="260" width="20" height="80" fill="#1f3a63"/><rect x="60" y="260" width="20" height="80" fill="#1f3a63"/><rect x="80" y="260" width="20" height="80" fill="#1f3a63"/><rect x="100" y="260" width="20" height="80" fill="#1f3a63"/><rect x="120" y="260" width="20" height="80" fill="#1f3a63"/><rect x="140" y="260" width="20" height="80" fill="#1f3a63"/><rect x="160" y="260" width="20" height="80" fill="#1f3a63"/><rect x="180" y="240" width="20" height="100" fill="#1f3a63"/><rect x="200" y="220" width="20" height="120" fill="#1f3a63"/><rect x="220" y="220" width="20" height="120" fill="#1f3a63"/><rect x="240" y="220" width="20" height="120" fill="#1f3a63"/><rect x="260" y="220" width="20" height="120" fill="#1f3a63"/><rect x="280" y="220" width="20" height="120" fill="#1f3a63"/><rect x="300" y="240" width="20" height="100" fill="#1f3a63"/><rect x="320" y="240" width="20" height="100" fill="#1f3a63"/><rect x="340" y="220" width="20" height="120" fill="#1f3a63"/><rect x="360" y="240" width="20" height="100" fill="#1f3a63"/><rect x="380" y="240" width="20" height="100" fill="#1f3a63"/><rect x="400" y="260" width="20" height="80" fill="#1f3a63"/><rect x="420" y="280" width="20" height="60" fill="#1f3a63"/><rect x="440" y="280" width="20" height="60" fill="#1f3a63"/><rect x="460" y="280" width="20" height="60" fill="#1f3a63"/><rect x="480" y="260" width="20" height="80" fill="#1f3a63"/><rect x="500" y="260" width="20" height="80" fill="#1f3a63"/><rect x="520" y="260" width="20" height="80" fill="#1f3a63"/><rect x="540" y="260" width="20" height="80" fill="#1f3a63"/><rect x="560" y="260" width="20" height="80" fill="#1f3a63"/><rect x="580" y="240" width="20" height="100" fill="#1f3a63"/><rect x="600" y="240" width="20" height="100" fill="#1f3a63"/><rect x="620" y="220" width="20" height="120" fill="#1f3a63"/><rect x="640" y="200" width="20" height="140" fill="#1f3a63"/><rect x="660" y="220" width="20" height="120" fill="#1f3a63"/><rect x="680" y="220" width="20" height="120" fill="#1f3a63"/><rect x="700" y="240" width="20" height="100" fill="#1f3a63"/><rect x="720" y="240" width="20" height="100" fill="#1f3a63"/><rect x="740" y="240" width="20" height="100" fill="#1f3a63"/><rect x="760" y="240" width="20" height="100" fill="#1f3a63"/><rect x="780" y="240" width="20" height="100" fill="#1f3a63"/><rect x="800" y="260" width="20" height="80" fill="#1f3a63"/><rect x="820" y="280" width="20" height="60" fill="#1f3a63"/><rect x="840" y="280" width="20" height="60" fill="#1f3a63"/><rect x="860" y="280" width="20" height="60" fill="#1f3a63"/><rect x="880" y="260" width="20" height="80" fill="#1f3a63"/><rect x="900" y="260" width="20" height="80" fill="#1f3a63"/><rect x="920" y="240" width="20" height="100" fill="#1f3a63"/><rect x="940" y="240" width="20" height="100" fill="#1f3a63"/><rect x="960" y="240" width="20" height="100" fill="#1f3a63"/><rect x="980" y="240" width="20" height="100" fill="#1f3a63"/><rect x="0" y="262" width="1000" height="78" fill="url(#hw)"/><rect x="490" y="266" width="100" height="6" fill="#fff1cb" opacity="0.75"/><rect x="500" y="279" width="80" height="6" fill="#fff1cb" opacity="0.63"/><rect x="510" y="292" width="60" height="6" fill="#fff1cb" opacity="0.51"/><rect x="518" y="305" width="44" height="6" fill="#fff1cb" opacity="0.39"/><rect x="526" y="318" width="28" height="6" fill="#fff1cb" opacity="0.27"/><rect x="0" y="220" width="20" height="20" fill="#4fd36a"/><rect x="0" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="0" y="260" width="20" height="80" fill="#6a4120"/><rect x="4" y="244" width="6" height="6" fill="#a8723a"/><rect x="20" y="220" width="20" height="20" fill="#4fd36a"/><rect x="20" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="20" y="260" width="20" height="80" fill="#6a4120"/><rect x="40" y="220" width="20" height="20" fill="#4fd36a"/><rect x="40" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="40" y="260" width="20" height="80" fill="#6a4120"/><rect x="60" y="220" width="20" height="20" fill="#4fd36a"/><rect x="60" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="60" y="260" width="20" height="80" fill="#6a4120"/><rect x="64" y="244" width="6" height="6" fill="#a8723a"/><rect x="80" y="220" width="20" height="20" fill="#4fd36a"/><rect x="80" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="80" y="260" width="20" height="80" fill="#6a4120"/><rect x="100" y="200" width="20" height="20" fill="#4fd36a"/><rect x="100" y="220" width="20" height="20" fill="#8b5a2b"/><rect x="100" y="240" width="20" height="100" fill="#6a4120"/><rect x="104" y="224" width="6" height="6" fill="#a8723a"/><rect x="120" y="200" width="20" height="20" fill="#4fd36a"/><rect x="120" y="220" width="20" height="20" fill="#8b5a2b"/><rect x="120" y="240" width="20" height="100" fill="#6a4120"/><rect x="140" y="200" width="20" height="20" fill="#4fd36a"/><rect x="140" y="220" width="20" height="20" fill="#8b5a2b"/><rect x="140" y="240" width="20" height="100" fill="#6a4120"/><rect x="144" y="224" width="6" height="6" fill="#a8723a"/><rect x="160" y="220" width="20" height="20" fill="#4fd36a"/><rect x="160" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="160" y="260" width="20" height="80" fill="#6a4120"/><rect x="180" y="240" width="20" height="20" fill="#4fd36a"/><rect x="180" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="180" y="280" width="20" height="60" fill="#6a4120"/><rect x="200" y="260" width="20" height="20" fill="#4fd36a"/><rect x="200" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="200" y="300" width="20" height="40" fill="#6a4120"/><rect x="220" y="260" width="20" height="20" fill="#4fd36a"/><rect x="220" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="220" y="300" width="20" height="40" fill="#6a4120"/><rect x="240" y="240" width="20" height="20" fill="#4fd36a"/><rect x="240" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="240" y="280" width="20" height="60" fill="#6a4120"/><rect x="244" y="264" width="6" height="6" fill="#a8723a"/><rect x="260" y="240" width="20" height="20" fill="#4fd36a"/><rect x="260" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="260" y="280" width="20" height="60" fill="#6a4120"/><rect x="280" y="240" width="20" height="20" fill="#4fd36a"/><rect x="280" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="280" y="280" width="20" height="60" fill="#6a4120"/><rect x="740" y="240" width="20" height="20" fill="#4fd36a"/><rect x="740" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="740" y="280" width="20" height="60" fill="#6a4120"/><rect x="760" y="220" width="20" height="20" fill="#4fd36a"/><rect x="760" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="760" y="260" width="20" height="80" fill="#6a4120"/><rect x="780" y="220" width="20" height="20" fill="#4fd36a"/><rect x="780" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="780" y="260" width="20" height="80" fill="#6a4120"/><rect x="784" y="244" width="6" height="6" fill="#a8723a"/><rect x="800" y="220" width="20" height="20" fill="#4fd36a"/><rect x="800" y="240" width="20" height="20" fill="#8b5a2b"/><rect x="800" y="260" width="20" height="80" fill="#6a4120"/><rect x="820" y="240" width="20" height="20" fill="#4fd36a"/><rect x="820" y="260" width="20" height="20" fill="#8b5a2b"/><rect x="820" y="280" width="20" height="60" fill="#6a4120"/><rect x="840" y="260" width="20" height="20" fill="#4fd36a"/><rect x="840" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="840" y="300" width="20" height="40" fill="#6a4120"/><rect x="860" y="260" width="20" height="20" fill="#4fd36a"/><rect x="860" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="860" y="300" width="20" height="40" fill="#6a4120"/><rect x="864" y="284" width="6" height="6" fill="#a8723a"/><rect x="880" y="260" width="20" height="20" fill="#4fd36a"/><rect x="880" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="880" y="300" width="20" height="40" fill="#6a4120"/><rect x="884" y="284" width="6" height="6" fill="#a8723a"/><rect x="900" y="260" width="20" height="20" fill="#4fd36a"/><rect x="900" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="900" y="300" width="20" height="40" fill="#6a4120"/><rect x="920" y="260" width="20" height="20" fill="#4fd36a"/><rect x="920" y="280" width="20" height="20" fill="#8b5a2b"/><rect x="920" y="300" width="20" height="40" fill="#6a4120"/><rect x="940" y="280" width="20" height="20" fill="#4fd36a"/><rect x="940" y="300" width="20" height="20" fill="#8b5a2b"/><rect x="940" y="320" width="20" height="20" fill="#6a4120"/><rect x="960" y="280" width="20" height="20" fill="#4fd36a"/><rect x="960" y="300" width="20" height="20" fill="#8b5a2b"/><rect x="960" y="320" width="20" height="20" fill="#6a4120"/><rect x="964" y="304" width="6" height="6" fill="#a8723a"/><rect x="980" y="280" width="20" height="20" fill="#4fd36a"/><rect x="980" y="300" width="20" height="20" fill="#8b5a2b"/><rect x="980" y="320" width="20" height="20" fill="#6a4120"/><rect x="984" y="304" width="6" height="6" fill="#a8723a"/><rect x="60" y="160" width="14" height="60" fill="#6b4220"/><rect x="47" y="120" width="40" height="20" fill="#2fae58"/><rect x="33" y="140" width="68" height="20" fill="#2fae58"/><rect x="33" y="160" width="68" height="20" fill="#2fae58"/><rect x="160" y="160" width="14" height="60" fill="#6b4220"/><rect x="147" y="120" width="40" height="20" fill="#2fae58"/><rect x="133" y="140" width="68" height="20" fill="#2fae58"/><rect x="133" y="160" width="68" height="20" fill="#2fae58"/><rect x="820" y="180" width="14" height="60" fill="#6b4220"/><rect x="807" y="140" width="40" height="20" fill="#2fae58"/><rect x="793" y="160" width="68" height="20" fill="#2fae58"/><rect x="793" y="180" width="68" height="20" fill="#2fae58"/><rect x="910" y="200" width="14" height="60" fill="#6b4220"/><rect x="897" y="160" width="40" height="20" fill="#2fae58"/><rect x="883" y="180" width="68" height="20" fill="#2fae58"/><rect x="883" y="200" width="68" height="20" fill="#2fae58"/><g opacity=".95"><polygon points="366,112 380,120 380,136 366,128" fill="#7c5cff"/><polygon points="380,120 394,112 394,128 380,136" fill="#4a35c9"/><polygon points="380,104 394,112 380,120 366,112" fill="#7dffb0"/><polygon points="650,84 660,90 660,101 650,96" fill="#7c5cff"/><polygon points="660,90 670,84 670,96 660,101" fill="#4a35c9"/><polygon points="660,79 670,84 660,90 650,84" fill="#7dffb0"/><polygon points="302,186 310,190 310,199 302,194" fill="#7c5cff"/><polygon points="310,190 318,186 318,194 310,199" fill="#4a35c9"/><polygon points="310,181 318,186 310,190 302,186" fill="#7dffb0"/></g></svg>',LOGO='<svg viewBox="-56 -64 112 114" width="46" height="47" aria-hidden="true"><defs><linearGradient id="ut" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#d6ffe7"/><stop offset="1" stop-color="#1bd96a"/></linearGradient><linearGradient id="ul" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8d70ff"/><stop offset="1" stop-color="#5a3fe0"/></linearGradient><linearGradient id="ur" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#5a3fe0"/><stop offset="1" stop-color="#2d1f8f"/></linearGradient></defs><polygon points="-26.0,-15.0 0.0,0.0 0.0,30.0 -26.0,15.0" fill="url(#ul)"/><polygon points="0.0,0.0 26.0,-15.0 26.0,15.0 0.0,30.0" fill="url(#ur)"/><polygon points="0.0,-30.0 26.0,-15.0 0.0,0.0 -26.0,-15.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="-52.0,0.0 -26.0,15.0 -26.0,45.0 -52.0,30.0" fill="url(#ul)"/><polygon points="-26.0,15.0 0.0,0.0 0.0,30.0 -26.0,45.0" fill="url(#ur)"/><polygon points="-26.0,-15.0 0.0,0.0 -26.0,15.0 -52.0,0.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="0.0,0.0 26.0,15.0 26.0,45.0 0.0,30.0" fill="url(#ul)"/><polygon points="26.0,15.0 52.0,0.0 52.0,30.0 26.0,45.0" fill="url(#ur)"/><polygon points="26.0,-15.0 52.0,0.0 26.0,15.0 0.0,0.0" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/><polygon points="-20.3,-47.7 0.0,-36.0 0.0,-12.6 -20.3,-24.3" fill="url(#ul)"/><polygon points="0.0,-36.0 20.3,-47.7 20.3,-24.3 0.0,-12.6" fill="url(#ur)"/><polygon points="0.0,-59.4 20.3,-47.7 0.0,-36.0 -20.3,-47.7" fill="url(#ut)" stroke="rgba(255,255,255,.35)" stroke-width="1"/></svg>';
const T=new URLSearchParams(location.search).get('t'),$=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Token':T,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});
 const d=await r.json();if(!r.ok)throw new Error(d.erreur||'Erreur');return d}
const qs=o=>'?'+new URLSearchParams(o);
function toast(m,bad){const d=document.createElement('div');d.className='toast'+(bad?' bad':'');d.textContent=m;$('#toasts').appendChild(d);setTimeout(()=>d.remove(),4800)}
async function run(fn){try{return await fn()}catch(e){toast(e.message,true)}}
const fmt=n=>Number(n).toLocaleString('fr-FR'),fmtK=n=>n>=1e6?(n/1e6).toFixed(1).replace('.',',')+' M':n>=1e3?Math.round(n/1e3)+' k':String(n);
const duree=s=>{s=s||0;const h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h?h+' h '+m+' min':m+' min'};
const VC={vert:'#22c55e',jaune:'#facc15',orange:'#fb923c',rouge:'#ef4444'};
const IC={accueil:'<path d="M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10"/>',jouer:'<rect x="3" y="3" width="18" height="18" rx="4"/><path d="M10 8l6 4-6 4z"/>',profils:'<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',mods:'<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',maps:'<path d="M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',reglages:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',boutique:'<path d="M6 8h12l1 12H5z"/><path d="M9 8a3 3 0 016 0"/>',actus:'<path d="M4 5h14v14H6a2 2 0 01-2-2z"/><path d="M18 9h2v8a2 2 0 01-2 2M8 9h6M8 13h6"/>',skins:'<path d="M8 4L3 7l2 4 3-1v10h8V10l3 1 2-4-5-3a4 4 0 01-8 0z"/>',perf:'<path d="M4 18a8 8 0 1116 0"/><path d="M12 18l4-6"/>',journal:'<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h7"/>',dossier:'<path d="M3 7h6l2 2h10v10H3z"/>',fichier:'<path d="M6 3h9l4 4v14H6z"/><path d="M9 12h7M9 16h7"/>',maj:'<path d="M20 12a8 8 0 11-3-6.2M20 4v4h-4"/>',repar:'<path d="M14 6a4 4 0 00-5 5l-6 6 3 3 6-6a4 4 0 005-5l-3 3-2-2z"/>',avance:'<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',serv:'<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/>'};
const ico=k=>`<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${IC[k]||''}</svg>`;
const NAV=[['accueil','Accueil'],['jouer','Jouer'],['profils','Profils'],['mods','Mods'],['maps','Maps'],['reglages','Paramètres'],['boutique','Boutique'],['actus','Actualités'],['skins','Skins'],['perf','Performance'],['journal','Journal']];
const CC={Vanilla:['#86e072','#8b5a2b','#6a4120'],Fabric:['#f3dcab','#c9a46a','#9f7d46'],Forge:['#ff9566','#c8452f','#8e2a1e']};
const cube=(l,s=40)=>{const c=CC[l]||CC.Vanilla;return `<svg width="${s}" height="${s}" viewBox="0 0 44 44"><polygon points="6,13 22,22 22,40 6,31" fill="${c[1]}"/><polygon points="22,22 38,13 38,31 22,40" fill="${c[2]}"/><polygon points="22,4 38,13 22,22 6,13" fill="${c[0]}"/></svg>`};
let lb=false,S={profils:[],serveurs:[],reglages:{},specs:{},compte:null,login:{},maj:{}},page='accueil',sel=0,genre='mods',R=[],MP=null,NW=null,last={running:false,busy:false},timerJ=null,boutiqueQ='';
const cur=()=>S.profils[Math.min(sel,S.profils.length-1)];
const vlist=async()=>{if(!S.versions)S.versions=(await api('/api/versions')).versions;return S.versions};
function renderSide(){
 $('#brand').innerHTML=LOGO+'<div><b>Lohyx Hub</b><small>Joue. Explore. Crée.</small></div>';
 $('#nav').innerHTML=NAV.map(([k,t])=>`<button class="${k==page?'on':''}" onclick="go('${k}')">${ico(k)}${t}</button>`).join('');
 const n=S.reglages.pseudo||'Joueur',c=S.compte;
 $('#me').innerHTML=`<img src="https://mc-heads.net/avatar/${encodeURIComponent(c?c.name:n)}/64" onerror="this.style.visibility='hidden'"><div><b>${esc(c?c.name:n)}</b><small><i class="${c?'':'off'}"></i>${c?'En ligne':'Hors-ligne'}</small></div>`;
 $('#me2').innerHTML=c?'<button class="btn" onclick="login()">⎋ Déconnexion</button>':'<button class="btn" onclick="login()">🔐 Connexion Microsoft</button>';
 $('#ver').textContent='v'+(S.version||'');
}
const go=p=>{page=p;clearInterval(timerJ);renderSide();render();$('#page').scrollTop=0};
const applyAccent=()=>document.documentElement.style.setProperty('--a',S.reglages.accent||'#7c6cff');
async function charger(){S=await api('/api/state');applyAccent();renderSide();renderMaj();render()}
function renderMaj(){const m=S.maj,b=$('#maj');if(m&&m.dispo){b.style.display='flex';b.innerHTML=`<span>🚀 <b>Mise à jour ${esc(m.version)}</b> disponible${m.notes&&m.notes.length?' — '+esc(m.notes[0]):''}</span><span class="sp"></span><button class="btn pri" onclick="majInstaller()">Mettre à jour</button><button class="btn" onclick="$('#maj').style.display='none'">Plus tard</button>`}else b.style.display='none'}
async function majInstaller(){toast('Téléchargement de la mise à jour…');const d=await run(()=>api('/api/maj/installer',{}));if(!d)return;
 if(d.manuel)return toast('La page de téléchargement s\'ouvre dans ton navigateur.');
 document.body.innerHTML='<div style="display:grid;place-items:center;height:100%;text-align:center;font-size:22px;line-height:1.7;color:#fff">🚀 Mise à jour installée !<br><span style="font-size:14px;color:#8f98c0">Lohyx Hub redémarre dans une nouvelle fenêtre.<br>Ferme celle-ci si elle reste ouverte.</span></div>';setTimeout(()=>window.close(),2500)}
function majVerifier(){if(!S.maj_actif)return toast('Mises à jour désactivées : adresse du site manquante (UPDATE_URL).',true);run(async()=>{const d=await api('/api/maj/verifier',{});await charger();toast(d.erreur?d.erreur:d.dispo?'Mise à jour '+d.version+' disponible !':'Tu as la dernière version ✔',!!d.erreur)})}
function render(){({accueil:pAccueil,jouer:pJouer,profils:pProfils,mods:pMods,maps:pMaps,reglages:pReglages,boutique:pBoutique,actus:pActus,skins:pSkins,perf:pPerf,journal:pJournal})[page]()}
const vbadge=v=>`<span class="pill"><i class="dot" style="background:${VC[v.niveau]};margin-right:7px"></i>${v.label}</span>`;
const bars=v=>v.details.map(d=>`<div class="bl"><b>${d.nom}</b><span>${esc(d.info)}</span></div><div class="bar"><i style="width:${Math.round(d.ratio*100)}%;background:${d.ratio>=.95?VC.vert:d.ratio>=.75?VC.jaune:d.ratio>=.55?VC.orange:VC.rouge}"></i></div>`).join('');
const url=u=>run(()=>api('/api/url',{url:u}));
function jouer(i,adresse){const p=S.profils[i];if(!p)return toast('Crée d\'abord un profil.',true);run(async()=>{await api('/api/jouer',{nom:p.nom,adresse});toast('Préparation de '+p.nom+'…')})}
async function modif(champ,val){const p=cur();if(!p)return;if((champ=='version'||champ=='loader')&&p.nb_mods&&!confirm('Changer la version ou le type peut rendre tes '+p.nb_mods+' mods incompatibles. Continuer ?')){render();return}
 await run(async()=>{await api('/api/profil/modifier',{nom:p.nom,[champ]:val});await charger()})}
const setReg=o=>run(async()=>{await api('/api/reglages',o);await charger()});
function setJava(v){if(v=='perso'){const c=prompt('Chemin complet de java.exe (ex : C:/Program Files/Java/jdk-21/bin/java.exe)');if(c)setReg({java:c});else render()}else setReg({java:''})}
function pingAll(cb){const l=S.serveurs;if(!l.length)return cb({on:0,total:0,joueurs:0});let on=0,j=0,done=0;l.forEach(s=>api('/api/ping',{adresse:s.adresse}).then(d=>{if(d.ok){on++;j+=d.online}}).catch(()=>{}).finally(()=>{if(++done==l.length)cb({on,total:l.length,joueurs:j})}))}
const wiki=v=>'https://minecraft.wiki/w/Java_Edition_'+encodeURIComponent((v||'').replace(/ /g,'_'));
const newsCard=n=>`<div class="glass card news" onclick="url('${wiki(n.version)}')" style="cursor:pointer">${n.image?`<img class="cv" src="${esc(n.image)}" onerror="this.remove()">`:''}<div class="row"><span class="tag2">${n.genre=='snapshot'?'Snapshot':'Version'}</span><span class="mut" style="font-size:12px">${esc(n.date)}</span></div><h4 style="margin:8px 0 4px">${esc(n.titre)}</h4><p class="mut" style="font-size:12.5px">${esc(n.resume).slice(0,140)}</p></div>`;

/* ---------- Accueil ---------- */
async function pAccueil(){const P=S.profils,p=cur();const V=await vlist();
 if(page!='accueil')return;
 const vers=p&&!V.includes(p.version)?[p.version,...V]:V;
 const hero=`<div class="hero"><div class="art">${HERO}</div><div class="hero-c"><div class="logotype">${LOGO.replace('width="46" height="47"','width="52" height="53"')}LOHYX HUB</div><div class="tag">Explorez, construisez, survivez…</div>
 <button class="play ${p?'v-'+p.verdict.niveau:'v-vert'}" ${p?'':'disabled'} onclick="jouer(sel)">▶ Jouer</button></div>
 <div class="selbar">${p?`<label>👤 Dernier profil : <select onchange="sel=+this.value;render()">${P.map((x,i)=>`<option value="${i}" ${i==sel?'selected':''}>${esc(x.nom)}</option>`).join('')}</select></label><i></i>
 <label>📦 Version : <select onchange="modif('version',this.value)">${vers.map(v=>`<option ${v==p.version?'selected':''}>${esc(v)}</option>`).join('')}</select></label><i></i>
 <label>⚙ <select onchange="modif('loader',this.value)">${['Vanilla','Fabric','Forge'].map(l=>`<option ${l==p.loader?'selected':''}>${l}</option>`).join('')}</select></label>`:'<label>Crée ton premier profil pour jouer</label>'}</div></div>`;
 const prow=`<div class="sec"><div class="hd">🔥 Mes profils <a onclick="go('profils')">Voir tout →</a></div><div class="prow"><div class="pc new" onclick="nouveauProfil()"><span>＋</span>Nouveau profil</div>
 ${P.slice(0,5).map((x,i)=>`<div class="pc ${i==sel?'on':''}" onclick="sel=${i};render()"><i class="dv" style="background:${VC[x.verdict.niveau]}" title="${esc(x.verdict.label)}"></i>${cube(x.loader,38)}<b>${esc(x.nom)}</b><small>${esc(x.version)} · ${x.loader}</small><span class="pl" onclick="event.stopPropagation();jouer(${i})">▶</span></div>`).join('')}</div></div>`;
 const mp=`<div class="sec"><div class="hd"><em>🔥</em> Modpacks populaires <a onclick="go('boutique')">Voir tout →</a></div><div class="mrow" id="mp"><div class="mut" style="grid-column:1/-1">Chargement…</div></div></div>`;
 const nw=`<div class="sec"><div class="hd">📅 Dernières actualités</div><div class="nrow" id="nw"><div class="mut">Chargement…</div></div></div>`;
 $('#page').innerHTML=`<div class="home"><div class="center">${hero}${prow}${mp}${nw}</div><div class="right" id="rc"></div></div>`;
 rightCol();loadMP();loadNews()}
function mpCard(m){return `<div class="mp"><div class="im">${m.icone?`<img src="${esc(m.icone)}" onerror="this.remove()">`:''}</div><div class="bd"><b>${esc(m.titre)}</b><div class="r2"><small>⬇ ${fmtK(m.dl)}</small><button class="dlb ${m.installe?'ok':''}" title="${m.installe?'Installé':m.compatible?'Installer ce modpack':'Fabric/Forge uniquement'}" onclick="installMP('${m.id}',this)">${m.installe?'✔':'⬇'}</button></div></div></div>`}
async function loadMP(){if(!MP){try{MP=(await api('/api/modpacks?limite=20')).modpacks}catch(e){MP=[]}}
 const el=$('#mp');if(!el)return;const l=MP.filter(m=>m.compatible).slice(0,5);el.innerHTML=l.length?l.map(mpCard).join(''):'<div class="mut" style="grid-column:1/-1">Modpacks indisponibles (pas de connexion ?).</div>'}
function installMP(id,b){const m=(MP||[]).find(x=>x.id==id);if(m&&m.installe)return;if(m&&!m.compatible)return toast('Ce modpack n\'est pas Fabric/Forge : pas encore géré.',true);
 run(async()=>{await api('/api/modpack/installer',{id});toast('Installation du modpack… (ça peut prendre quelques minutes)')})}
async function loadNews(){if(!NW){try{NW=(await api('/api/news')).news}catch(e){NW=[]}}
 const el=$('#nw');if(!el)return;if(!NW.length){el.innerHTML='<div class="mut">Actualités indisponibles (pas de connexion ?).</div>';return}
 const n=NW[0];el.innerHTML=`<div class="nbig">${n.image?`<img src="${esc(n.image)}" onerror="this.remove()">`:''}<div style="min-width:0"><h4>${esc(n.titre)}</h4><p>${esc(n.resume).slice(0,170)}</p><div class="ft">${esc(n.date)}<button class="btn" onclick="url('${wiki(n.version)}')">Lire la suite →</button></div></div></div>
 <div class="nlist">${NW.slice(1,4).map(x=>`<div class="ni" onclick="url('${wiki(x.version)}')">${x.image?`<img src="${esc(x.image)}" onerror="this.remove()">`:''}<div style="min-width:0"><b>${esc(x.titre)}</b><small>${esc(x.date)}</small></div></div>`).join('')}</div>`}
function rightCol(){const p=cur(),r=S.reglages,el=$('#rc');if(!el)return;
 const rmax=Math.max(2,Math.floor((S.ram_systeme||8)-2)),rams=[2,4,6,8,12,16,24,32].filter(x=>x<=rmax),pr=p?(p.ram||r.ram):r.ram;if(!rams.includes(pr))rams.push(pr);rams.sort((a,b)=>a-b);
 const res=['1280x720','1600x900','1920x1080','2560x1440'];if(!res.includes(r.resolution))res.push(r.resolution);
 const nom=S.compte?S.compte.name:r.pseudo;
 el.innerHTML=`<div class="rc"><div class="hd">👤 Profil actuel<span class="gear" onclick="go('profils')">⚙</span></div>
 ${p?`<div class="cur"><div class="cv">${cube(p.loader,40)}</div><div><b>${esc(p.nom)}</b><div class="st" style="cursor:pointer" onclick="go('perf')" title="${esc(p.verdict.message)}"><i class="dot" style="background:${VC[p.verdict.niveau]}"></i>${p.verdict.niveau=='vert'?'Prêt à jouer':esc(p.verdict.label)}</div></div></div>
 <div class="mini"><div><small>Version</small><b>${esc(p.version)}</b></div><div><small>Loader</small><b>${p.loader}</b></div><div><small>Mods</small><b>${p.nb_mods} mods</b></div></div>`:'<p class="mut" style="margin:12px 0;font-size:13px">Aucun profil pour l\'instant.</p>'}
 <button class="btn" style="width:100%" onclick="go('profils')">👤 Gérer les profils</button></div>
 <div class="rc"><details open><summary>⚙ Paramètres rapides</summary><div class="qs">
 <span>🖥 Résolution</span><select onchange="setReg({resolution:this.value})">${res.map(x=>`<option ${x==r.resolution?'selected':''}>${x}</option>`).join('')}</select>
 <span>⛶ Écran plein</span><label class="sw"><input type="checkbox" ${r.plein_ecran?'checked':''} onchange="setReg({plein_ecran:this.checked})"><i></i></label>
 <span>📈 FPS max</span><select onchange="setReg({fps:+this.value})">${[[0,'illimité'],[30,'30'],[60,'60'],[120,'120'],[144,'144'],[240,'240']].map(([v,t])=>`<option value="${v}" ${v==r.fps?'selected':''}>${t}</option>`).join('')}</select>
 <span>🧠 Mémoire (RAM)</span><select ${p?'':'disabled'} onchange="modif('ram',this.value)">${rams.map(x=>`<option value="${x}" ${x==pr?'selected':''}>${x} Go</option>`).join('')}</select>
 <span>☕ Java</span><select onchange="setJava(this.value)"><option value="auto" ${r.java?'':'selected'}>Auto (recommandé)</option><option value="perso" ${r.java?'selected':''}>${r.java?'Personnalisé':'Personnalisé…'}</option></select></div></details></div>
 <div class="rc"><details open><summary>🔗 Raccourcis</summary><div class="sc">
 <a onclick="run(()=>api('/api/ouvrir_racine',{}))">${ico('dossier')}Dossier .minecraft</a><a onclick="go('journal')">${ico('fichier')}Ouvrir les logs</a>
 <a onclick="majVerifier()">${ico('maj')}Vérifier les mises à jour</a><a onclick="reparer()">${ico('repar')}Réparer l'installation</a><a onclick="go('reglages')">${ico('avance')}Paramètres avancés</a></div></details></div>
 <div class="rc"><div class="srvbox"><span style="color:#4ade80">${ico('serv')}</span><div style="flex:1">Serveurs en ligne<b id="srvn">…</b></div><span style="color:#4ade80;font-size:20px">▂▄▆</span></div></div>`;
 pingAll(d=>{const e=$('#srvn');if(e)e.textContent=d.total?`${d.on}/${d.total} · ${d.joueurs} joueur${d.joueurs>1?'s':''}`:'Aucun serveur ajouté'})}
function reparer(){const p=cur();if(!p)return toast('Crée d\'abord un profil.',true);if(confirm('Réparer l\'installation de Minecraft '+p.version+' ?\nLes fichiers du jeu seront retéléchargés au prochain lancement. Tes mondes et tes mods ne sont pas touchés.'))run(async()=>{const d=await api('/api/reparer',{nom:p.nom});toast(d.retire.length?'Réparation prête : relance le jeu pour retélécharger.':'Rien à réparer : le jeu n\'est pas encore installé.')})}

/* ---------- Jouer ---------- */
function pJouer(){const P=S.profils,p=cur();
 $('#page').innerHTML=`<div class="pg"><h1>Jouer</h1>${p?`<div class="glass card row" style="gap:26px;margin-top:16px;padding:22px"><div style="flex:1;min-width:280px"><div class="row nw">${cube(p.loader,54)}<div><h2 style="margin:0">${esc(p.nom)}</h2><div class="mut" style="font-size:13px">Minecraft ${esc(p.version)} · ${p.loader} · ${p.nb_mods} mods · ${p.ram||S.reglages.ram} Go</div></div></div>
 <div style="margin:18px 0"><button class="play v-${p.verdict.niveau}" onclick="jouer(sel)">▶ Jouer</button></div><div class="verdict v-${p.verdict.niveau}" style="max-width:520px"><b>${p.verdict.label}</b> — ${esc(p.verdict.message)}</div></div><div style="width:280px">${bars(p.verdict)}</div></div>
 <div class="row" style="margin-top:12px">${P.map((x,i)=>`<span class="pc" style="height:auto;flex-direction:row;padding:8px 14px;${i==sel?'border-color:#7c6cff;background:#161c42':''}" onclick="sel=${i};render()">${esc(x.nom)}</span>`).join('')}</div>`:'<p class="mut" style="margin:14px 0">Crée un profil pour commencer.</p><button class="btn pri" onclick="nouveauProfil()">＋ Nouveau profil</button>'}
 <div class="row" style="margin-top:28px"><h2 style="margin:0">Rejoindre un serveur</h2><span class="sp"></span><button class="btn" onclick="pJouer()">↻ Actualiser</button><button class="btn pri" onclick="ajoutSrv()">＋ Ajouter</button></div>
 <div class="grid" style="margin-top:12px">${S.serveurs.length?S.serveurs.map((s,i)=>`<div class="glass card"><div class="row nw"><h2 style="margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.nom)}</h2><span class="sp"></span><span class="pill" id="sv${i}"><i class="dot" style="background:#667;margin-right:7px"></i>…</span></div><div class="mut" style="font-size:12.5px;margin:4px 0 10px">${esc(s.adresse)}</div><div id="sm${i}" class="mut" style="font-size:12.5px;min-height:18px;margin-bottom:10px"></div><div class="row"><button class="btn pri" onclick="jouer(sel,'${esc(s.adresse)}')">Rejoindre</button><button class="btn red" onclick="retSrv(${i})">Retirer</button></div></div>`).join(''):'<div class="mut">Aucun serveur. Clique sur « Ajouter » (ex : mc.hypixel.net).</div>'}</div></div>`;
 S.serveurs.forEach((s,i)=>api('/api/ping',{adresse:s.adresse}).then(d=>{if(!$('#sv'+i))return;$('#sv'+i).innerHTML=d.ok?`<i class="dot" style="background:${VC.vert};margin-right:7px"></i>${d.online}/${d.max} · ${d.ms} ms`:`<i class="dot" style="background:${VC.rouge};margin-right:7px"></i>Hors ligne`;if(d.ok)$('#sm'+i).textContent=d.motd+(d.version?'  ·  '+d.version:'')}))}
function ajoutSrv(){modal(`<h2>Ajouter un serveur</h2><label class="l">Nom</label><input class="full" id="s-n" placeholder="Mon serveur"><label class="l">Adresse</label><input class="full" id="s-a" placeholder="mc.exemple.fr"><div class="row" style="margin-top:20px"><span class="sp"></span><button class="btn" onclick="fermer()">Annuler</button><button class="btn pri" onclick="addSrv()">Ajouter</button></div>`)}
const addSrv=()=>run(async()=>{await api('/api/serveur/ajouter',{nom:$('#s-n').value,adresse:$('#s-a').value});fermer();await charger()});
const retSrv=i=>run(async()=>{await api('/api/serveur/retirer',{adresse:S.serveurs[i].adresse});await charger()});

/* ---------- Profils ---------- */
function pProfils(){const P=S.profils;
 $('#page').innerHTML=`<div class="pg"><div class="row"><h1>Mes profils</h1><span class="sp"></span><button class="btn pri" onclick="nouveauProfil()">＋ Nouveau profil</button></div><p class="mut" style="margin:6px 0 18px">Le bouton Jouer change de couleur selon la puissance de ton PC pour ce profil.</p>
 <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(360px,1fr))">${P.length?P.map((p,i)=>`<div class="glass card"><div class="row nw">${cube(p.loader,34)}<h2 style="margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.nom)}</h2><span class="sp"></span>${vbadge(p.verdict)}</div><div class="mut" style="margin:8px 0 14px;font-size:12.5px">Minecraft ${esc(p.version)} · ${p.loader} · ${p.nb_mods} mods${p.shaders?' · shaders':''}${p.modpack?' · modpack':''}<br>${p.ram||S.reglages.ram} Go de RAM · ${duree(p.temps)} de jeu</div>
 <div class="row nw"><button class="play sm v-${p.verdict.niveau}" onclick="jouer(${i})">▶ JOUER</button><button class="btn ic2" title="Mods" onclick="sel=${i};go('mods')">🧩</button><button class="btn ic2" title="Modifier" onclick="editer(${i})">✏️</button><button class="btn ic2" title="Dossier" onclick="ouvrir(${i})">📁</button><button class="btn ic2" title="Sauvegarder les mondes" onclick="sauver(${i})">💾</button><button class="btn red ic2" title="Supprimer" onclick="suppr(${i})">🗑</button></div></div>`).join(''):'<div class="mut">Aucun profil. Clique sur « Nouveau profil ».</div>'}</div></div>`}
const ouvrir=i=>run(()=>api('/api/profil/ouvrir',{nom:S.profils[i].nom}));
const sauver=(i,monde)=>run(async()=>{await api('/api/sauvegarde',{nom:S.profils[i].nom,monde});toast('Sauvegarde créée ✔')});
function suppr(i){const p=S.profils[i];if(confirm('Supprimer « '+p.nom+' » ?\nSes mondes et ses mods seront effacés.'))run(async()=>{await api('/api/profil/supprimer',{nom:p.nom});sel=0;await charger()})}
function modal(h){$('#mbox').innerHTML=h;$('#modal').classList.add('on')}
const fermer=()=>$('#modal').classList.remove('on');
const ramMax=()=>Math.max(2,Math.min(32,Math.floor((S.ram_systeme||8)-2)));
async function nouveauProfil(){const v=await run(()=>api('/api/versions'));if(!v)return;const max=ramMax();
 modal(`<h2>Nouveau profil</h2><label class="l">Nom</label><input class="full" id="m-nom" maxlength="30" placeholder="Mon aventure"><label class="l">Type</label><div class="seg" id="m-type">${['Vanilla','Fabric','Forge'].map((t,i)=>`<button class="${i==1?'on':''}" onclick="seg(this)">${t}</button>`).join('')}</div>
 <label class="l">Version de Minecraft</label><select class="full" id="m-ver" onchange="apercu()">${v.versions.map(x=>`<option>${x}</option>`).join('')}</select>
 <label class="l">Mémoire : <b id="m-rv">${Math.min(4,max)}</b> Go</label><input class="full" type="range" id="m-ram" min="1" max="${max}" value="${Math.min(4,max)}" oninput="$('#m-rv').textContent=this.value">
 <div id="m-v" style="margin-top:16px"></div><div class="row" style="margin-top:20px"><span class="sp"></span><button class="btn" onclick="fermer()">Annuler</button><button class="btn pri" onclick="creer()">Créer</button></div>`);apercu()}
function seg(b){b.parentNode.querySelectorAll('button').forEach(x=>x.classList.remove('on'));b.classList.add('on');if($('#m-ver'))apercu()}
function apercu(){const l=document.querySelector('#m-type .on').textContent,v=$('#m-ver').value;api('/api/verdict'+qs({version:v,loader:l})).then(d=>{if($('#m-v'))$('#m-v').innerHTML=`<div class="verdict v-${d.niveau}" style="margin:0"><b>${d.label}</b> — ${esc(d.message)}</div>`}).catch(()=>{})}
const creer=()=>run(async()=>{await api('/api/profil/creer',{nom:$('#m-nom').value,version:$('#m-ver').value,loader:document.querySelector('#m-type .on').textContent,ram:$('#m-ram').value});fermer();sel=S.profils.length;await charger();go('profils');toast('Profil créé ✔')});
async function editer(i){const p=S.profils[i],V=await vlist(),vers=V.includes(p.version)?V:[p.version,...V];
 modal(`<h2>Modifier « ${esc(p.nom)} »</h2><label class="l">Type</label><div class="seg" id="e-type">${['Vanilla','Fabric','Forge'].map(t=>`<button class="${t==p.loader?'on':''}" onclick="seg(this)">${t}</button>`).join('')}</div><label class="l">Version</label><select class="full" id="e-ver">${vers.map(v=>`<option ${v==p.version?'selected':''}>${esc(v)}</option>`).join('')}</select>
 <label class="l">Mémoire : <b id="e-rv">${p.ram||S.reglages.ram}</b> Go</label><input class="full" type="range" id="e-ram" min="1" max="${Math.max(ramMax(),p.ram||4)}" value="${p.ram||S.reglages.ram}" oninput="$('#e-rv').textContent=this.value">
 ${p.nb_mods?`<p class="mut" style="font-size:12px;margin-top:12px">⚠ Changer la version ou le type peut rendre tes ${p.nb_mods} mods incompatibles.</p>`:''}<div class="row" style="margin-top:20px"><span class="sp"></span><button class="btn" onclick="fermer()">Annuler</button><button class="btn pri" onclick="sauverEd(${i})">Enregistrer</button></div>`)}
const sauverEd=i=>run(async()=>{await api('/api/profil/modifier',{nom:S.profils[i].nom,loader:document.querySelector('#e-type .on').textContent,version:$('#e-ver').value,ram:$('#e-ram').value});fermer();await charger();toast('Profil modifié ✔')});

/* ---------- Mods ---------- */
function pMods(){const p=cur();if(!p){$('#page').innerHTML='<div class="pg"><h1>Mods</h1><p class="mut" style="margin-top:10px">Crée d\'abord un profil.</p></div>';return}
 $('#page').innerHTML=`<div class="pg"><h1>Mods, shaders & packs</h1><div class="row" style="margin-top:14px"><div style="width:250px"><select class="full" onchange="sel=this.value;pMods()">${S.profils.map((x,i)=>`<option value="${i}" ${i==sel?'selected':''}>${esc(x.nom)} (${x.version} ${x.loader})</option>`).join('')}</select></div>${vbadge(p.verdict)}</div>
 <div class="tabs">${[['mods','Mods'],['shaders','Shaders'],['packs','Packs de ressources']].map(([k,t])=>`<button class="${k==genre?'on':''}" onclick="genre='${k}';pMods()">${t}</button>`).join('')}</div>
 ${genre=='mods'&&p.loader=='Fabric'?`<div class="glass card row" style="margin-bottom:14px"><div><b>🚀 Boost FPS</b><div class="mut" style="font-size:12.5px">Installe Sodium, Lithium, FerriteCore, EntityCulling et ModernFix en un clic.</div></div><span class="sp"></span><button class="btn pri" onclick="boost()">Installer</button></div>`:''}
 ${genre=='shaders'?`<div class="mut" style="font-size:12.5px;margin-bottom:12px">Les shaders demandent le mod Iris (cherche « iris » dans l'onglet Mods) et une bonne carte graphique.</div>`:''}
 <div class="row"><input id="q" placeholder="Rechercher… (ex : sodium)" onkeydown="if(event.key=='Enter')chercher()" style="flex:1"><button class="btn pri" onclick="chercher()">Rechercher</button></div>
 <div class="grid" id="res" style="margin-top:14px"></div><h3>Déjà installés</h3><div id="inst"></div></div>`;chercher();installes()}
const modBtn=(m,i)=>m.installe?`<button class="btn ok" disabled>✔ Installé</button>`:`<button class="btn pri" onclick="inst(${i},this)">Installer</button>`;
function chercher(){const p=cur();$('#res').innerHTML='<div class="mut">Recherche…</div>';
 api('/api/chercher'+qs({nom:p.nom,genre,q:$('#q').value})).then(d=>{R=d.resultats;$('#res').innerHTML=R.length?R.map((m,i)=>`<div class="glass mod"><img src="${esc(m.icone)}" onerror="this.style.visibility='hidden'"><div style="min-width:0"><h4>${esc(m.titre)}</h4><p>${esc(m.desc)}</p><div class="row" id="mb${i}">${modBtn(m,i)}<span class="mut" style="font-size:12px">⬇ ${fmtK(m.dl)}</span></div></div></div>`).join(''):'<div class="mut">Aucun résultat pour cette version.</div>'}).catch(e=>{$('#res').innerHTML=`<div class="mut">${esc(e.message)}</div>`})}
function inst(i,b){const p=cur();b.textContent='Installation…';b.disabled=true;run(async()=>{try{await api('/api/installer',{nom:p.nom,id:R[i].id,genre,titre:R[i].titre});R[i].installe=true;const e=$('#mb'+i);if(e)e.firstElementChild.outerHTML=modBtn(R[i],i);toast(R[i].titre+' installé ✔');await charger()}catch(err){b.disabled=false;b.textContent='Installer';throw err}})}
function boost(){const p=cur();toast('Installation du Boost FPS…');run(async()=>{const d=await api('/api/boost',{nom:p.nom});toast('Boost FPS : '+d.n+' mods installés ✔');await charger()})}
function installes(){const p=cur();api('/api/installes'+qs({nom:p.nom,genre})).then(d=>{$('#inst').innerHTML=d.fichiers.length?d.fichiers.map(f=>`<div class="glass row" style="padding:9px 15px;margin-bottom:6px"><span style="font-size:13.5px">${esc(d.titres[f]||f)}${d.titres[f]?`<small class="mut" style="margin-left:9px">${esc(f)}</small>`:''}</span><span class="sp"></span><button class="btn red" onclick="retirer('${esc(f).replace(/'/g,'')}')">Retirer</button></div>`).join(''):'<div class="mut">Rien d\'installé ici.</div>'}).catch(()=>{})}
function retirer(f){const p=cur();run(async()=>{await api('/api/retirer',{nom:p.nom,genre,fichier:f});await charger();if(page=='mods')pMods()})}

/* ---------- Maps ---------- */
function pMaps(){$('#page').innerHTML='<div class="pg"><h1>Maps</h1><p class="mut" style="margin:6px 0 18px">Tes mondes, profil par profil. Sauvegarde-les en un clic (fichier zip).</p><div id="mm" class="mut">Chargement…</div></div>';
 api('/api/mondes').then(d=>{const el=$('#mm');if(!el)return;if(!d.mondes.length){el.innerHTML='<div class="glass card">Aucun monde pour l\'instant. Lance une partie et crée un monde : il apparaîtra ici.</div>';return}
  el.className='';el.innerHTML=d.mondes.map(m=>{const i=S.profils.findIndex(p=>p.nom==m.profil);return `<div class="glass row" style="padding:12px 16px;margin-bottom:8px"><div style="font-size:26px">🗺️</div><div><b>${esc(m.nom)}</b><div class="mut" style="font-size:12px">${esc(m.profil)} · ${m.taille} Mo · modifié le ${m.modifie}</div></div><span class="sp"></span><button class="btn" onclick="sauver(${i},'${esc(m.nom).replace(/'/g,'')}')">💾 Sauvegarder</button><button class="btn ic2" title="Ouvrir le dossier des mondes" onclick="run(()=>api('/api/profil/ouvrir',{nom:'${esc(m.profil).replace(/'/g,'')}',sous:'saves'}))">📁</button></div>`}).join('')}).catch(e=>{$('#mm').textContent=e.message})}

/* ---------- Boutique (modpacks) ---------- */
function pBoutique(){$('#page').innerHTML=`<div class="pg"><h1>Boutique</h1><p class="mut" style="margin:6px 0 16px">Des modpacks prêts à jouer, depuis Modrinth. Un clic crée un profil avec tout dedans (Fabric et Forge).</p>
 <div class="row"><input id="bq" placeholder="Chercher un modpack… (ex : create, adventure)" value="${esc(boutiqueQ)}" style="flex:1" onkeydown="if(event.key=='Enter')cherchePacks()"><button class="btn pri" onclick="cherchePacks()">Rechercher</button></div><div class="grid" id="bm" style="margin-top:16px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))"><div class="mut">Chargement…</div></div></div>`;cherchePacks()}
function cherchePacks(){boutiqueQ=$('#bq')?$('#bq').value:'';api('/api/modpacks'+qs({q:boutiqueQ,limite:24})).then(d=>{MP=d.modpacks;const el=$('#bm');if(!el)return;
 el.innerHTML=MP.length?MP.map(m=>`<div class="mp"><div class="im" style="height:110px">${m.icone?`<img src="${esc(m.icone)}" onerror="this.remove()">`:''}</div><div style="padding:11px"><b style="display:block;font-size:13.5px">${esc(m.titre)}</b><p class="mut" style="font-size:12px;margin:4px 0 8px;height:34px;overflow:hidden">${esc(m.desc)}</p><div class="row nw"><small class="mut">⬇ ${fmtK(m.dl)}</small>${m.loaders.map(l=>`<span class="tag2">${l}</span>`).join('')}<span class="sp"></span>${m.installe?'<button class="btn ok ic2" disabled>✔ Installé</button>':m.compatible?`<button class="btn pri ic2" onclick="installMP('${m.id}',this)">Installer</button>`:'<button class="btn ic2" disabled title="NeoForge/Quilt : pas encore géré">Non géré</button>'}</div></div></div>`).join(''):'<div class="mut">Aucun modpack trouvé.</div>'}).catch(e=>{const el=$('#bm');if(el)el.innerHTML=`<div class="mut">${esc(e.message)}</div>`})}

/* ---------- Skins ---------- */
function pSkins(){const n=S.compte?S.compte.name:S.reglages.pseudo;
 $('#page').innerHTML=`<div class="pg"><h1>Skins</h1><div class="row" style="align-items:flex-start;gap:28px;margin-top:18px"><div class="glass" style="width:250px;height:420px;display:grid;place-items:center" id="skb"><img src="https://mc-heads.net/body/${encodeURIComponent(n)}/260" style="max-height:380px" onerror="this.outerHTML='<span class=mut>Skin introuvable</span>'"></div>
 <div style="flex:1;min-width:280px"><label class="l" style="margin-top:0">Pseudo du joueur</label><div class="row"><input id="sk-n" value="${esc(n)}" style="flex:1" onkeydown="if(event.key=='Enter')voirSkin()"><button class="btn pri" onclick="voirSkin()">Voir</button></div>
 <div class="row" style="margin-top:12px"><button class="btn" onclick="url('https://namemc.com/profile/'+encodeURIComponent($('#sk-n').value))">NameMC</button><button class="btn" onclick="url('https://www.minecraft.net/fr-fr/msaprofile/mygames/editskin')">Changer mon skin</button></div>
 <div class="glass card" style="margin-top:20px"><b>Skin en mode hors-ligne</b><p class="mut" style="font-size:12.5px;margin:6px 0 12px">Sans compte Microsoft, Minecraft n'affiche pas ton skin. CustomSkinLoader le rend visible.</p>
 <div class="row"><select id="sk-p" style="width:220px">${S.profils.filter(x=>x.loader!='Vanilla').map(x=>`<option>${esc(x.nom)}</option>`).join('')||'<option value="">(aucun profil Fabric/Forge)</option>'}</select><button class="btn pri" onclick="skinMod()">Installer le mod</button></div></div></div></div></div>`}
function voirSkin(){const n=$('#sk-n').value.trim();if(!/^\w{3,16}$/.test(n))return toast('Pseudo invalide.',true);$('#skb').innerHTML=`<img src="https://mc-heads.net/body/${encodeURIComponent(n)}/260" style="max-height:380px" onerror="this.outerHTML='<span class=mut>Skin introuvable</span>'">`}
function skinMod(){const n=$('#sk-p').value;if(!n)return toast('Crée un profil Fabric ou Forge.',true);toast('Installation…');run(async()=>{await api('/api/skinmod',{nom:n});toast('Mod de skins installé ✔')})}

/* ---------- Actus / Perf / Journal / Réglages ---------- */
function pActus(){$('#page').innerHTML='<div class="pg"><h1>Actualités Minecraft</h1><div class="grid" style="margin-top:18px" id="ac"><div class="mut">Chargement…</div></div></div>';
 api('/api/news').then(d=>{NW=d.news;$('#ac').innerHTML=d.news.map(newsCard).join('')}).catch(e=>{$('#ac').innerHTML='<div class="mut">Impossible de charger les actualités : '+esc(e.message)+'</div>'})}
function pPerf(){api('/api/perf').then(d=>{const s=d.specs,c=x=>`<td>${vbadge(x)}</td>`;
 $('#page').innerHTML=`<div class="pg"><h1>Performance de ton PC</h1><p class="mut" style="margin:6px 0 16px">Lohyx Hub compare ton matériel à ce que demande chaque version de Minecraft.</p>
 <div class="stats"><div class="glass stat"><b>${s.ram?s.ram+' Go':'…'}</b><span>Mémoire (RAM)</span></div><div class="glass stat"><b>${s.threads||'…'}</b><span>Threads processeur</span></div><div class="glass stat"><b style="font-size:15px">${esc((s.gpus||['…'])[0])}</b><span>Carte graphique</span></div></div>
 <h3>Légende</h3><div class="row" style="gap:22px">${[['vert','Parfait'],['jaune','Il faut se calmer'],['orange','Pas assez puissant'],['rouge','Quasi impossible']].map(([k,t])=>`<span class="pill"><i class="dot" style="background:${VC[k]};margin-right:7px"></i>${t}</span>`).join('')}</div>
 <h3>Verdict par version</h3><div class="glass" style="padding:8px 14px"><table><tr><th>Version</th><th>Vanilla</th><th>Avec ~60 mods</th><th>Avec shaders</th></tr>${d.lignes.map(l=>`<tr><td><b>${l.version}</b></td>${c(l.vanilla)}${c(l.mods)}${c(l.shaders)}</tr>`).join('')}</table></div></div>`}).catch(e=>toast(e.message,true))}
function pJournal(){$('#page').innerHTML='<div class="pg"><div class="row"><h1>Journal du jeu</h1><span class="sp"></span><span class="mut" style="font-size:12px">mis à jour toutes les 3 s</span></div><pre id="lg" style="margin-top:14px"></pre></div>';
 const f=()=>api('/api/log').then(d=>{const e=$('#lg');if(e){e.textContent=d.log;e.scrollTop=e.scrollHeight}});f();timerJ=setInterval(f,3000)}
function pReglages(){const r=S.reglages,cols=['#7c6cff','#1bd96a','#00b7ff','#ff4d8d','#ffb020','#ff5a36'];
 $('#page').innerHTML=`<div class="pg"><h1>Paramètres</h1><div class="grid" style="margin-top:18px"><div class="glass card"><h2>Joueur</h2><label class="l">Pseudo (mode hors-ligne)</label><input class="full" id="r-p" value="${esc(r.pseudo)}" ${S.compte?'disabled':''}><label class="l">RAM par défaut : <b id="r-v">${r.ram}</b> Go</label><input class="full" type="range" id="r-r" min="1" max="${ramMax()}" value="${Math.min(r.ram,ramMax())}" oninput="$('#r-v').textContent=this.value"><div style="margin-top:16px"><button class="btn pri" onclick="saveR()">Enregistrer</button></div></div>
 <div class="glass card"><h2>Couleur</h2><div class="row" style="margin-top:12px">${cols.map(c=>`<div class="sws ${c==r.accent?'on':''}" style="background:${c}" onclick="setReg({accent:'${c}'})"></div>`).join('')}</div></div>
 <div class="glass card"><h2>Compte Minecraft</h2>${S.compte?`<p class="mut" style="margin:6px 0 14px">Connecté : <b style="color:var(--txt)">${esc(S.compte.name)}</b></p><button class="btn red" onclick="login()">Se déconnecter</button>`
 :`<p class="mut" style="font-size:12.5px;margin:6px 0 14px;line-height:1.5">Une page officielle de Microsoft s'ouvre : connecte-toi avec le compte qui possède Minecraft Java, puis reviens ici.</p><button class="btn pri" style="width:100%;padding:12px" onclick="login()">🔐 Se connecter à votre compte Minecraft</button>${S.login.msg?`<p style="font-size:12.5px;margin-top:12px;color:var(--orange)">${esc(S.login.msg)}</p>`:''}${S.login_ok?'':'<p style="font-size:12px;margin-top:12px;color:var(--orange);line-height:1.5">⚠ Aucun Client ID Microsoft dans ce launcher : il faut le coller une fois dans la ligne CLIENT_ID de LohyxHub.pyw.</p>'}<details style="margin-top:12px"><summary class="mut" style="font-size:12px;cursor:pointer">Avancé : coller un Client ID</summary><input class="full" id="r-c" placeholder="Client ID Azure" style="margin-top:8px"></details>`}</div>
 <div class="glass card"><h2>À propos</h2><p class="mut" style="margin:6px 0 14px">Lohyx Hub <b style="color:var(--txt)">version ${esc(S.version)}</b></p>${S.maj_actif?`<button class="btn" onclick="majVerifier()">Vérifier les mises à jour</button>`:'<p class="mut" style="font-size:12.5px;line-height:1.5">Mises à jour automatiques désactivées. Mets l\'adresse de ton site dans la ligne UPDATE_URL de LohyxHub.pyw.</p>'}</div></div></div>`}
const saveR=()=>run(async()=>{const b={ram:+$('#r-r').value};if(!S.compte)b.pseudo=$('#r-p').value;await api('/api/reglages',b);await charger();toast('Enregistré ✔')});
function login(){if(S.compte&&!confirm('Te déconnecter de ton compte Minecraft ?'))return;run(async()=>{await api('/api/login',{client_id:$('#r-c')?$('#r-c').value:''});if(!S.compte)toast('Une page Microsoft s\'ouvre dans ton navigateur…');await charger()})}

/* ---------- Boucle de progression ---------- */
setInterval(async()=>{try{const p=await api('/api/progress');
 $('#prog').style.display=p.busy?'flex':'none';$('#fst').textContent=p.status;$('#fbar').style.width=p.pct+'%';$('#fpc').textContent=p.pct?p.pct+' %':'';
 if(p.error)toast(p.error,true);if(!last.running&&p.running)toast('Minecraft est lancé ! Bon jeu 🎮');
 if((last.running&&!p.running)||(last.busy&&!p.busy)){MP=null;await charger()}last=p;
 if(S.login.busy||lb){const was=lb;await charger();lb=S.login.busy;if(was&&!lb)S.compte?toast('Connecté en tant que '+S.compte.name+' ✔'):S.login.msg&&toast(S.login.msg,true)}}catch(e){}},1000);
renderSide();charger();
</script></body></html>
"""

if __name__ == "__main__":
    main()
