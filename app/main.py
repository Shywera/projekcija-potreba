"""Samostalni Nabava app - jednokorisnicki, bez prijave/sesija (svjesna odluka, vidi CLAUDE.md).

Prati PAUK export (rucni upload) i za svaki konfigurirani artikl racuna treba li se
naruciti (fali = max(0, min - nak_nar)) te crta punu projekciju zalihe kroz vrijeme
(trosenje iz radnih naloga + dolazak iz narudzbi). v2: cuva POVIJEST svih uploada
(arhiva + povijesni graf), ne samo zadnji.

Tablice se kreiraju na startu (`create_all`); na svakom startu radi se auto-backup.

Pokretanje:  .venv\\Scripts\\uvicorn app.main:app   (ili run.bat / dev-wifi.bat)
"""
from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import inspect as sa_inspect, text

from app.core.backup import auto_backup, db_putanja
from app.core.database import Base, engine
from app.modules.nabava import models  # noqa: F401 - registrira Artikl/Snapshot/StanjeSnapshot/Dogadjaj
from app.modules.nabava.routes import router as nabava_router
from app.modules.nabava.seed import seed_artikli_ako_prazno
from app.modules.nabava.service import uploads_dir

auto_backup()                          # backup postojece baze prije starta
Base.metadata.create_all(bind=engine)


def _migracija() -> None:
    """Idempotentne migracije (isti obrazac kao WMS-app/Reklamacije-app): create_all pokriva
    NOVE tablice, ali ne nove stupce na postojecim - ti se dodaju ovdje diffom protiv
    sa_inspect(...).get_columns(...). v1->v2: snapshot dobiva datoteka/aktivan, dogadjaj
    dobiva snapshot_id, a stari 'artikl_stanje' se preslikava u 'stanje_snapshot' pa dropa."""
    insp = sa_inspect(engine)
    tablice = set(insp.get_table_names())

    def stupci(t):
        return {c["name"] for c in insp.get_columns(t)} if t in tablice else set()

    dodaj = []
    if "snapshot" in tablice:
        sc = stupci("snapshot")
        if "datoteka" not in sc:
            dodaj.append("ALTER TABLE snapshot ADD COLUMN datoteka VARCHAR(400)")
        if "aktivan" not in sc:
            dodaj.append("ALTER TABLE snapshot ADD COLUMN aktivan BOOLEAN DEFAULT 0")
    if "dogadjaj" in tablice and "snapshot_id" not in stupci("dogadjaj"):
        dodaj.append("ALTER TABLE dogadjaj ADD COLUMN snapshot_id INTEGER")
    for sql in dodaj:
        with engine.begin() as conn:
            conn.execute(text(sql))

    # v2->v3: artikl_id postaje NULLABLE (spremamo SVE materijale iz exporta, ne samo pracene).
    # SQLite ne moze ALTER COLUMN, pa se te dvije tablice rekreiraju - podaci su regenerabilni
    # iz sirovih .xlsx u uploads/ (vidi service.preracunaj_iz_arhive, pokrece se nize).
    insp2 = sa_inspect(engine)
    tab2 = set(insp2.get_table_names())
    treba_preracun = False
    for tablica in ("stanje_snapshot", "dogadjaj"):
        if tablica not in tab2:
            continue
        stupac = next((c for c in insp2.get_columns(tablica) if c["name"] == "artikl_id"), None)
        if stupac is not None and not stupac["nullable"]:
            with engine.begin() as conn:
                conn.execute(text(f"DROP TABLE {tablica}"))
            treba_preracun = True
    if treba_preracun:
        Base.metadata.create_all(bind=engine)   # ponovno kreiraj s novom shemom
        print("[Nabava] Shema azurirana (svi materijali). Preracunavam arhivu iz uploads/...")

    # Jednokratna, non-destruktivna migracija v1 podataka: ako je nova stanje_snapshot prazna
    # a stari artikl_stanje postoji -> preslikaj retke (vezano uz postojeci/aktivni snapshot),
    # pa dropaj deprecated tablicu. Tako v1 test-snapshot postane 1. povijesna tocka.
    tablice = set(sa_inspect(engine).get_table_names())
    if "artikl_stanje" in tablice and "stanje_snapshot" in tablice:
        with engine.begin() as conn:
            ima_novih = conn.execute(text("SELECT COUNT(*) FROM stanje_snapshot")).scalar() or 0
            ima_starih = conn.execute(text("SELECT COUNT(*) FROM artikl_stanje")).scalar() or 0
            if ima_novih == 0 and ima_starih > 0:
                snap_id = conn.execute(
                    text("SELECT id FROM snapshot ORDER BY ucitano_at DESC LIMIT 1")
                ).scalar()
                if snap_id is not None:
                    conn.execute(text("UPDATE snapshot SET aktivan = 1 WHERE id = :i"), {"i": snap_id})
                    conn.execute(text(
                        "INSERT INTO stanje_snapshot (snapshot_id, artikl_id, sifra, naziv, "
                        "dobavljac, stanje, nak_rn, nak_nar, fali, status, prvi_pad_datum, "
                        "prvi_pad_dani, oporavlja_li_se, datum_oporavka, odstupa_od_erp) "
                        "SELECT :snap, artikl_id, sifra, naziv, dobavljac, stanje, nak_rn, nak_nar, "
                        "fali, status, prvi_pad_datum, prvi_pad_dani, oporavlja_li_se, "
                        "datum_oporavka, odstupa_od_erp FROM artikl_stanje"),
                        {"snap": snap_id})
                    # dogadjaji iz v1 nemaju snapshot_id -> vezi ih uz taj snapshot
                    conn.execute(text("UPDATE dogadjaj SET snapshot_id = :i WHERE snapshot_id IS NULL"),
                                 {"i": snap_id})
            conn.execute(text("DROP TABLE artikl_stanje"))

    return treba_preracun


_treba_preracun = _migracija()
seed_artikli_ako_prazno()
uploads_dir()  # osiguraj da uploads/ postoji

if _treba_preracun:
    from app.core.database import SessionLocal
    from app.modules.nabava.service import preracunaj_iz_arhive
    _db = SessionLocal()
    try:
        _r = preracunaj_iz_arhive(_db)
        print(f"[Nabava] Preracunato snapshota: {_r['preracunato']}, greske: {len(_r['greske'])}")
    finally:
        _db.close()

app = FastAPI(title="Nabava", docs_url="/api-docs", redoc_url=None)
app.include_router(nabava_router)


@app.get("/backup", include_in_schema=False)
def backup():
    """Preuzmi kopiju trenutne baze. Bez auth-a (nema korisnika) - vidi CLAUDE.md."""
    p = db_putanja()
    if p is None or not p.exists():
        return PlainTextResponse("Baza ne postoji.", status_code=404)
    return FileResponse(p, filename=p.name, media_type="application/octet-stream")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/nabava")
