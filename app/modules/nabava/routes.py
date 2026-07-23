from datetime import datetime

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.nabava import pdf as pdf_modul, service
from app.modules.nabava.models import Artikl, Dogadjaj, Snapshot, StanjeSnapshot

router = APIRouter(prefix="/nabava", tags=["nabava"])
templates = Jinja2Templates(directory="app/templates")


def _kategorije(db: Session) -> list[str]:
    return sorted({a.kategorija for a in db.scalars(select(Artikl)).all()})


def _parse_sifra_forma(form) -> dict:
    kategorija = str(form.get("kategorija", "")).strip()
    sifra = str(form.get("sifra", "")).strip()
    napomena = str(form.get("napomena", "")).strip() or None
    min_tip = str(form.get("min_tip", "BROJ"))
    min_broj = None
    if min_tip == "BROJ":
        raw = str(form.get("min_broj", "")).strip().replace(",", ".")
        try:
            min_broj = float(raw)
        except ValueError:
            min_broj = 0.0
    try:
        redoslijed = int(str(form.get("redoslijed", "")).strip())
    except ValueError:
        redoslijed = 0
    return dict(kategorija=kategorija, sifra=sifra, min_tip=min_tip, min_broj=min_broj,
                napomena=napomena, redoslijed=redoslijed)


# ─── Dashboard ──────────────────────────────────────────────────────────────

@router.get("", response_class=HTMLResponse)
def dashboard(request: Request, snapshot: int | None = None, db: Session = Depends(get_db)):
    snap = db.get(Snapshot, snapshot) if snapshot else service.aktivni_snapshot(db)
    ukupno_snapshota = db.scalar(select(func.count(Snapshot.id))) or 0

    artikli = list(db.scalars(select(Artikl).order_by(Artikl.redoslijed)).all())
    # kljuc je SIFRA (ne artikl_id) - snapshot sad sadrzi i materijale izvan popisa pracenih
    # kojima je artikl_id None, pa bi kljucanje po artikl_id sve njih sudaralo na None.
    stanja_po_sifri = {}
    if snap and artikli:
        stanja_po_sifri = {s.sifra: s for s in db.scalars(
            select(StanjeSnapshot).where(StanjeSnapshot.snapshot_id == snap.id,
                                          StanjeSnapshot.sifra.in_([a.sifra for a in artikli]))
        ).all()}

    redci = []
    for a in artikli:
        st = stanja_po_sifri.get(a.sifra)
        stil = service.stil_statusa(st.status, st.prvi_pad_dani, st.oporavlja_li_se) if st else None
        redci.append({"kategorija": a.kategorija, "artikl": a, "stanje": st, "stil": stil})

    grupe = service.grupiraj_po_kategoriji(redci)
    rekap = sorted(
        (r for r in redci if r["stanje"] and r["stanje"].fali > 0),
        key=lambda r: (r["stanje"].dobavljac or ""),
    )
    # KPI brojevi za stat-trake
    broj_naruci = len(rekap)
    broj_pada = sum(1 for r in redci if r["stil"] and r["stil"]["tip"] in ("critical", "serious"))

    starost_sati = None
    if snap and snap.datum_exporta:
        starost_sati = (datetime.now() - snap.datum_exporta).total_seconds() / 3600

    return templates.TemplateResponse(request, "nabava/dashboard.html", {
        "snapshot": snap, "grupe": grupe, "rekap": rekap, "starost_sati": starost_sati,
        "broj_naruci": broj_naruci, "broj_pada": broj_pada, "broj_artikala": len(artikli),
        "ukupno_snapshota": ukupno_snapshota,
        "gleda_stari": bool(snapshot) and snap is not None and not snap.aktivan,
    })


# ─── Pretraga po sifri/nazivu (SVI materijali iz exporta, ne samo praceni) ──

@router.get("/trazi", response_class=HTMLResponse)
def trazi(request: Request, q: str = "", db: Session = Depends(get_db)):
    q = (q or "").strip()
    snap = service.aktivni_snapshot(db)
    rezultati, previse = [], False
    if q and snap:
        uzorak = f"%{q}%"
        redci = list(db.scalars(
            select(StanjeSnapshot)
            .where(StanjeSnapshot.snapshot_id == snap.id)
            .where(StanjeSnapshot.sifra.like(uzorak) | StanjeSnapshot.naziv.ilike(uzorak))
            .order_by(StanjeSnapshot.sifra).limit(201)
        ).all())
        previse = len(redci) > 200
        redci = redci[:200]
        praceni = {a.sifra for a in db.scalars(select(Artikl)).all()}
        rezultati = [{"st": r, "praceni": r.sifra in praceni,
                      "stil": service.stil_statusa(r.status, r.prvi_pad_dani, r.oporavlja_li_se)}
                     for r in redci]
    return templates.TemplateResponse(request, "nabava/trazi.html", {
        "q": q, "rezultati": rezultati, "previse": previse, "snapshot": snap,
    })


# ─── PDF izvoz (kao stari desktop izvjestaj) ────────────────────────────────

@router.get("/pdf")
def preuzmi_pdf(db: Session = Depends(get_db)):
    if service.aktivni_snapshot(db) is None:
        return PlainTextResponse("Nema ucitanih podataka za PDF.", status_code=404)
    data, naziv = pdf_modul.generiraj_pdf(db)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{naziv}"'})


# ─── Upload ─────────────────────────────────────────────────────────────────

@router.get("/ucitaj", response_class=HTMLResponse)
def ucitaj_forma(request: Request):
    return templates.TemplateResponse(request, "nabava/ucitaj.html", {"greska": None})


@router.post("/ucitaj")
async def ucitaj_obradi(request: Request, datoteka: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    data = await datoteka.read()
    try:
        service.obradi_upload(db, datoteka.filename, data)
    except Exception as e:
        return templates.TemplateResponse(request, "nabava/ucitaj.html", {
            "greska": f"Ne mogu procitati datoteku (je li ovo PAUK export?): {e}",
        }, status_code=400)
    return RedirectResponse("/nabava", status_code=303)


# ─── Arhiva (povijest uploada) ──────────────────────────────────────────────

@router.get("/arhiva", response_class=HTMLResponse)
def arhiva(request: Request, db: Session = Depends(get_db)):
    snapshoti = list(db.scalars(select(Snapshot).order_by(Snapshot.ucitano_at.desc())).all())
    # broj artikala po snapshotu (za prikaz)
    broj_po_snap = dict(db.execute(
        select(StanjeSnapshot.snapshot_id, func.count(StanjeSnapshot.id))
        .group_by(StanjeSnapshot.snapshot_id)
    ).all())
    return templates.TemplateResponse(request, "nabava/arhiva.html", {
        "snapshoti": snapshoti, "broj_po_snap": broj_po_snap,
    })


@router.get("/arhiva/{snap_id}/preuzmi")
def arhiva_preuzmi(snap_id: int, db: Session = Depends(get_db)):
    snap = db.get(Snapshot, snap_id)
    if snap is None or not snap.datoteka:
        return PlainTextResponse("Datoteka za ovaj upload nije spremljena.", status_code=404)
    from pathlib import Path
    p = Path(snap.datoteka)
    if not p.exists():
        return PlainTextResponse("Datoteka nije pronadena na disku.", status_code=404)
    return FileResponse(p, filename=snap.izvor_naziv or p.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/arhiva/{snap_id}/aktiviraj")
def arhiva_aktiviraj(snap_id: int, db: Session = Depends(get_db)):
    snap = db.get(Snapshot, snap_id)
    if snap is not None:
        db.query(Snapshot).update({Snapshot.aktivan: False})
        snap.aktivan = True
        db.commit()
    return RedirectResponse("/nabava", status_code=303)


@router.post("/arhiva/{snap_id}/obrisi")
def arhiva_obrisi(snap_id: int, db: Session = Depends(get_db)):
    snap = db.get(Snapshot, snap_id)
    if snap is not None:
        # obrisi spremljeni file
        if snap.datoteka:
            from pathlib import Path
            try:
                Path(snap.datoteka).unlink()
            except OSError:
                pass
        bio_aktivan = snap.aktivan
        db.query(StanjeSnapshot).filter(StanjeSnapshot.snapshot_id == snap_id).delete()
        db.query(Dogadjaj).filter(Dogadjaj.snapshot_id == snap_id).delete()
        db.delete(snap)
        db.commit()
        # ako je obrisan aktivni, aktiviraj najnoviji preostali
        if bio_aktivan:
            zadnji = db.scalar(select(Snapshot).order_by(Snapshot.ucitano_at.desc()).limit(1))
            if zadnji is not None:
                zadnji.aktivan = True
                db.commit()
    return RedirectResponse("/nabava/arhiva", status_code=303)


# ─── Sifre (CRUD konfiguracije) ────────────────────────────────────────────

@router.get("/sifre", response_class=HTMLResponse)
def sifre_popis(request: Request, db: Session = Depends(get_db)):
    artikli = list(db.scalars(select(Artikl).order_by(Artikl.redoslijed)).all())
    grupe = service.grupiraj_po_kategoriji(artikli)
    # nazivi dolaze iz aktivnog exporta (StanjeSnapshot), ne iz konfiguracije
    snap = service.aktivni_snapshot(db)
    naziv_po_sifri = {}
    if snap and artikli:
        naziv_po_sifri = {s.sifra: s.naziv for s in db.scalars(
            select(StanjeSnapshot).where(StanjeSnapshot.snapshot_id == snap.id,
                                          StanjeSnapshot.sifra.in_([a.sifra for a in artikli]))).all()}
    return templates.TemplateResponse(request, "nabava/sifre.html",
                                      {"grupe": grupe, "naziv_po_sifri": naziv_po_sifri})


@router.get("/sifre/nova", response_class=HTMLResponse)
def sifra_nova_forma(request: Request, sifra: str = "", db: Session = Depends(get_db)):
    sljedeci = (db.scalar(select(func.max(Artikl.redoslijed))) or 0) + 10
    return templates.TemplateResponse(request, "nabava/sifre_forma.html", {
        "a": None, "kategorije": _kategorije(db), "sljedeci_redoslijed": sljedeci,
        "greska": None, "prefill_sifra": sifra,   # iz pretrage: "dodaj u pracene"
    })


@router.post("/sifre/nova")
async def sifra_nova_spremi(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    podaci = _parse_sifra_forma(form)
    greska = None
    if not podaci["sifra"] or not podaci["kategorija"]:
        greska = "Sifra i kategorija su obavezne."
    elif db.scalar(select(Artikl).where(Artikl.sifra == podaci["sifra"])):
        greska = f"Sifra {podaci['sifra']} vec postoji."
    if greska:
        return templates.TemplateResponse(request, "nabava/sifre_forma.html", {
            "a": None, "kategorije": _kategorije(db),
            "sljedeci_redoslijed": podaci["redoslijed"], "greska": greska,
        }, status_code=400)
    db.add(Artikl(**podaci))
    db.commit()
    return RedirectResponse("/nabava/sifre", status_code=303)


@router.get("/sifre/{artikl_id}/uredi", response_class=HTMLResponse)
def sifra_uredi_forma(artikl_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Artikl, artikl_id)
    if a is None:
        return RedirectResponse("/nabava/sifre", status_code=303)
    return templates.TemplateResponse(request, "nabava/sifre_forma.html", {
        "a": a, "kategorije": _kategorije(db), "sljedeci_redoslijed": a.redoslijed, "greska": None,
    })


@router.post("/sifre/{artikl_id}/uredi")
async def sifra_uredi_spremi(artikl_id: int, request: Request, db: Session = Depends(get_db)):
    a = db.get(Artikl, artikl_id)
    if a is None:
        return RedirectResponse("/nabava/sifre", status_code=303)
    form = await request.form()
    podaci = _parse_sifra_forma(form)
    greska = None
    if not podaci["sifra"] or not podaci["kategorija"]:
        greska = "Sifra i kategorija su obavezne."
    else:
        sukob = db.scalar(select(Artikl).where(Artikl.sifra == podaci["sifra"], Artikl.id != artikl_id))
        if sukob:
            greska = f"Sifra {podaci['sifra']} vec postoji na drugom artiklu."
    if greska:
        return templates.TemplateResponse(request, "nabava/sifre_forma.html", {
            "a": a, "kategorije": _kategorije(db), "sljedeci_redoslijed": a.redoslijed, "greska": greska,
        }, status_code=400)
    for k, v in podaci.items():
        setattr(a, k, v)
    db.commit()
    return RedirectResponse("/nabava/sifre", status_code=303)


@router.post("/sifre/{artikl_id}/obrisi")
def sifra_obrisi(artikl_id: int, db: Session = Depends(get_db)):
    """Micanje s popisa PRACENIH ne brise podatke o materijalu - oni ostaju u arhivi
    (materijal i dalje postoji u exportu i moze mu se pogledati graf kroz pretragu).
    Samo se raskine veza (artikl_id -> None) pa obrise konfiguracijski red."""
    a = db.get(Artikl, artikl_id)
    if a is not None:
        db.query(StanjeSnapshot).filter(StanjeSnapshot.artikl_id == artikl_id)\
            .update({StanjeSnapshot.artikl_id: None})
        db.query(Dogadjaj).filter(Dogadjaj.artikl_id == artikl_id)\
            .update({Dogadjaj.artikl_id: None})
        db.delete(a)
        db.commit()
    return RedirectResponse("/nabava/sifre", status_code=303)


# ─── Detalj artikla (kombinirani graf: povijest + projekcija) ───────────────

@router.get("/artikl/{sifra}", response_class=HTMLResponse)
def artikl_detalj(sifra: str, request: Request, db: Session = Depends(get_db)):
    # `a` (konfiguracija) moze biti None - detalj radi i za materijale IZVAN popisa pracenih
    # (tada nema minimuma pa ni linije praga; sve ostalo - graf, povijest, dogadjaji - radi).
    a = db.scalar(select(Artikl).where(Artikl.sifra == sifra))

    snap = service.aktivni_snapshot(db)
    st = None
    dogadjaji = []
    krivulja = {"povijest": [], "projekcija": [], "danas": None}
    stil = None
    if snap:
        st = db.scalar(select(StanjeSnapshot).where(
            StanjeSnapshot.sifra == sifra, StanjeSnapshot.snapshot_id == snap.id))
        dogadjaji = list(db.scalars(
            select(Dogadjaj).where(Dogadjaj.sifra == sifra, Dogadjaj.snapshot_id == snap.id)
            .order_by(Dogadjaj.datum)
        ).all())
        krivulja = service.kombinirana_krivulja(db, sifra, snap, st)
        if st:
            stil = service.stil_statusa(st.status, st.prvi_pad_dani, st.oporavlja_li_se)

    if a is None and st is None:
        return RedirectResponse("/nabava/trazi?q=" + sifra, status_code=303)

    sibling_krpe = []
    if a is not None and a.min_tip == "COMB_3":
        sibling_krpe = [x.sifra for x in db.scalars(
            select(Artikl).where(Artikl.min_tip == "COMB_3", Artikl.id != a.id)
        ).all()]

    return templates.TemplateResponse(request, "nabava/detalj.html", {
        "a": a, "sifra": sifra, "stanje": st, "stil": stil, "dogadjaji": dogadjaji,
        "krivulja": krivulja, "sibling_krpe": sibling_krpe, "snapshot": snap,
    })
