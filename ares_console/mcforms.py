"""SitRepNet / JS8Spotter MCForms support.

Form file syntax (MCFxxx.txt):
    Title|F!NNN          first line
    # comment            ignored
    ! / !! / !!!         headings
    . text               information text
    ? Question           multiple-choice question
    @X Option            option code X, '*' before text marks the default
    [XX] Label           free-text field with tag XX
"""
import glob
import io
import os
import re
import urllib.request
import zipfile

ZIP_INDEX = "https://sitrepnet.com/js8spotter-mcforms-repository/"
ZIP_FALLBACK = "https://sitrepnet.com/mcforms/MCForms20260714.zip"


def parse(text):
    lines = text.replace("\r", "").split("\n")
    title, fid = lines[0].split("|", 1) if "|" in lines[0] else (lines[0], "")
    items = []
    q = None
    for ln in lines[1:]:
        s = ln.rstrip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("?"):
            q = {"type": "choice", "label": s[1:].strip(), "options": [], "default": None}
            items.append(q)
        elif s.startswith("@") and q is not None and len(s) >= 2:
            code = s[1]
            label = s[2:].strip()
            if label.startswith("*"):
                label = label[1:].strip()
                q["default"] = code
            q["options"].append({"code": code, "label": label})
        elif s.startswith("["):
            m = re.match(r"\[(\w+)\]\s*(.*)", s)
            if m:
                items.append({"type": "text", "tag": m.group(1), "label": m.group(2)})
            q = None
        elif s.startswith("!"):
            lvl = len(s) - len(s.lstrip("!"))
            items.append({"type": "heading", "level": lvl, "label": s.lstrip("!").strip()})
            q = None
        elif s.startswith("."):
            t = s[1:].strip()
            if t:
                items.append({"type": "info", "label": t})
    return {"title": title.strip(), "id": fid.strip(), "items": items}


def encode(form, answers):
    """Build the compact report string and a readable expansion.

    answers: {"q<index>": code, "t<TAG>": text}
    The compact form is FORMID + one code per question, followed by any text fields
    as [TAG]value.  (Matches the JS8Spotter MCForms layout of one character per answer.)
    """
    codes = []
    texts = []
    readable = ["%s %s" % (form["id"], form["title"])]
    qi = 0
    for it in form["items"]:
        if it["type"] == "choice":
            c = answers.get("q%d" % qi) or it.get("default") or "?"
            qi += 1
            codes.append(c)
            lab = next((o["label"] for o in it["options"] if o["code"] == c), "(no answer)")
            readable.append("%s: %s" % (it["label"], lab))
        elif it["type"] == "text":
            v = (answers.get("t" + it["tag"]) or "").strip()
            if v:
                texts.append("[%s]%s" % (it["tag"], v))
            readable.append("%s: %s" % (it["label"], v))
    compact = form["id"] + " " + "".join(codes)
    if texts:
        compact += " " + " ".join(texts)
    return compact, "\n".join(readable)


def forms_dir(base):
    return os.path.join(base, "mcforms")


def load_all(base):
    out = {}
    for p in sorted(glob.glob(os.path.join(forms_dir(base), "*.txt"))):
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                frm = parse(fh.read())
            if frm["id"]:
                frm["file"] = os.path.basename(p)
                out[frm["id"]] = frm
        except Exception:  # noqa
            continue
    return out


def download(base):
    """Download the current MCForms ZIP from SitRepNet and extract the .txt forms."""
    url = ZIP_FALLBACK
    try:
        html = urllib.request.urlopen(urllib.request.Request(ZIP_INDEX, headers={"User-Agent": "ARES-Console"}),
                                      timeout=20).read().decode("utf-8", "replace")
        m = re.findall(r"https?://sitrepnet\.com/mcforms/MCForms\d+\.zip", html)
        if m:
            url = sorted(m)[-1]
    except Exception:  # noqa
        pass
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ARES-Console"}),
                                  timeout=60).read()
    d = forms_dir(base)
    os.makedirs(d, exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            bn = os.path.basename(name)
            if re.fullmatch(r"MCF[\w-]*\.txt", bn, re.I):
                with open(os.path.join(d, bn), "wb") as fh:
                    fh.write(z.read(name))
                n += 1
    return {"url": url, "count": n}
