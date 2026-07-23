"""PDF izvjestaj za nabavu - "kao onaj prije" (desktop Tjedna usklada): rekapitulacija za
nabavu (grupirano po dobavljacu) + detaljna tablica po kategorijama sa statusom. Layout
prenesen iz desktop alata (0.4), podaci iz aktivnog snapshota (StanjeSnapshot)."""
from datetime import datetime

from fpdf import FPDF
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.nabava import service
from app.modules.nabava.models import Artikl, Snapshot, StanjeSnapshot

# sirine stupaca detaljne tablice (landscape A4, ~277mm iskoristivo)
# Sifra, Naziv, Min, Na skladistu, Slobodno, S narucenim, Naruci, Status
W = [38, 68, 14, 24, 22, 26, 22, 63]

# boja statusa po semantickom tipu (ista paleta kao web badge)
BOJA_TIP = {
    "critical": (208, 59, 59), "serious": (236, 131, 90), "info": (42, 120, 214),
    "muted": (137, 135, 129), "ok": (12, 163, 12),
}


def _ascii(tekst, n=None):
    """Transliteracija hr znakova (built-in fpdf font je latin-1) + opcionalno skracivanje."""
    t = str.maketrans({'č': 'c', 'Č': 'C', 'ć': 'c', 'Ć': 'C', 'ž': 'z', 'Ž': 'Z',
                       'š': 's', 'Š': 'S', 'đ': 'dj', 'Đ': 'Dj'})
    s = str(tekst or "").translate(t).strip()
    if n and len(s) > n:
        s = s[:n - 3] + "..."
    return s


class _PDF(FPDF):
    def __init__(self, naslov_datuma):
        super().__init__(orientation="L", unit="mm", format="A4")
        self._datum = naslov_datuma
        self._zaglavlje = False
        self.set_auto_page_break(auto=True, margin=12)
        self.set_line_width(0.2)

    def header(self):
        if not self._zaglavlje:
            return
        self.set_font("Courier", "B", 13)
        self.cell(0, 9, "NABAVA - DETALJI", 0, 1, "C")
        self.set_font("Courier", "", 8)
        self.set_text_color(110, 110, 110)
        self.cell(0, 5, f"Podaci iz PAUK exporta: {self._datum}", 0, 1, "C")
        self.set_font("Courier", "", 7)
        self.cell(0, 4, "Na skladistu = fizicki kod nas | Slobodno = nakon rezervacija za radne naloge"
                        " | S narucenim = slobodno + vec naruceno (roba jos moze biti kod dobavljaca)",
                  0, 1, "C")
        self.set_text_color(0)
        self.ln(1)
        self.set_font("Courier", "B", 8)
        self.set_fill_color(210, 210, 210)
        naslovi = [" Sifra", " Naziv", " Min", " Na skladistu", " Slobodno", " S narucenim",
                   " Naruci", " Status"]
        for w, n in zip(W, naslovi):
            self.cell(w, 8, n, 1, 0, "L", True)
        self.ln()

    def footer(self):
        self.set_y(-10)
        self.set_font("Courier", "", 7)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Stranica {self.page_no()}", 0, 0, "C")
        self.set_text_color(0)


def generiraj_pdf(db: Session) -> tuple[bytes, str]:
    """Vraca (bajtovi_pdf, naziv_datoteke). Cita aktivni snapshot + konfiguraciju."""
    snap = service.aktivni_snapshot(db)
    datum_txt = (snap.datum_exporta.strftime("%d.%m.%Y. %H:%M")
                 if snap and snap.datum_exporta else "(nepoznat)")

    artikli = list(db.scalars(select(Artikl).order_by(Artikl.redoslijed)).all())
    # kljuc po SIFRI (snapshot sadrzi i materijale izvan popisa, kojima je artikl_id None)
    stanja = {}
    if snap and artikli:
        stanja = {s.sifra: s for s in db.scalars(
            select(StanjeSnapshot).where(StanjeSnapshot.snapshot_id == snap.id,
                                          StanjeSnapshot.sifra.in_([a.sifra for a in artikli]))).all()}

    # redci: artikl + stanje + stil (status)
    redci = []
    for a in artikli:
        st = stanja.get(a.sifra)
        stil = service.stil_statusa(st.status, st.prvi_pad_dani, st.oporavlja_li_se) if st else None
        redci.append({"artikl": a, "kategorija": a.kategorija, "stanje": st, "stil": stil})

    rekap = sorted((r for r in redci if r["stanje"] and r["stanje"].fali > 0),
                   key=lambda r: (r["stanje"].dobavljac or ""))

    pdf = _PDF(datum_txt)

    # --- Stranica 1: Rekapitulacija za nabavu ---
    pdf.add_page()
    pdf.set_font("Courier", "B", 15)
    pdf.cell(0, 12, "REKAPITULACIJA ZA NABAVU", 0, 1, "C")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 5, f"Podaci iz PAUK exporta: {datum_txt}", 0, 1, "C")
    pdf.set_text_color(0)
    pdf.ln(4)

    if not rekap:
        pdf.set_font("Courier", "B", 12)
        pdf.cell(0, 10, "SVE JE NA STANJU. NEMA POTREBE ZA NARUDZBOM.", 0, 1, "L")
    else:
        zadnji = None
        for r in rekap:
            st, a = r["stanje"], r["artikl"]
            if st.dobavljac != zadnji:
                zadnji = st.dobavljac
                pdf.ln(1)
                pdf.set_font("Courier", "B", 11)
                pdf.set_fill_color(240, 240, 240)
                pdf.cell(277, 9, _ascii(f" {st.dobavljac or '(nepoznat dobavljac)'}", 90), 1, 1, "L", True)
            pdf.set_font("Courier", "", 10)
            pdf.set_text_color(0)
            hitno = a.min_tip in ("POSITIVE", "COMB_3")
            kol = "HITNO" if hitno else f"{st.fali:,.2f}"
            if hitno:
                pdf.set_text_color(200, 0, 0)
            pdf.cell(55, 8, _ascii(f" {a.sifra}"), 1)
            pdf.cell(182, 8, _ascii(f" {st.naziv}", 92), 1)
            pdf.cell(40, 8, kol, 1, 1, "R")
            pdf.set_text_color(0)

    # --- Detalji po kategorijama ---
    pdf._zaglavlje = True
    pdf.add_page()
    grupe = service.grupiraj_po_kategoriji(redci)
    for kategorija, grupa in grupe:
        pdf.set_font("Courier", "B", 10)
        pdf.set_fill_color(210, 210, 210)
        pdf.set_text_color(0)
        pdf.cell(sum(W), 8, _ascii(f"--- {kategorija} ---"), 1, 1, "C", True)
        for r in grupa:
            _red_detalj(pdf, r)

    izlaz = pdf.output()  # bytes (fpdf2)
    naziv = f"Nabava_{datetime.now().strftime('%d.%m.%Y')}.pdf"
    return bytes(izlaz), naziv


def _red_detalj(pdf, r):
    a, st, stil = r["artikl"], r["stanje"], r["stil"]
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(0)
    pdf.set_fill_color(255, 255, 255)

    pdf.cell(W[0], 7, _ascii(f" {a.sifra}"), 1)
    if st is None:
        pdf.set_text_color(180, 90, 30)
        pdf.cell(sum(W[1:]), 7, "  nije pronadjeno u ovom exportu", 1, 1)
        pdf.set_text_color(0)
        return

    pdf.cell(W[1], 7, _ascii(f" {st.naziv}", 37), 1)
    min_s = ("%g" % a.min_broj) if a.min_tip == "BROJ" else (">0" if a.min_tip == "POSITIVE" else "Sum>=3")
    pdf.cell(W[2], 7, min_s, 1, 0, "C")
    pdf.cell(W[3], 7, f"{st.stanje:,.2f}", 1, 0, "R")      # Na skladistu
    pdf.cell(W[4], 7, f"{st.nak_rn:,.2f}", 1, 0, "R")      # Slobodno
    pdf.cell(W[5], 7, f"{st.nak_nar:,.2f}", 1, 0, "R")     # S narucenim

    if st.fali > 0:
        pdf.set_text_color(200, 0, 0)
        val = f"{st.fali:,.2f}" if a.min_tip not in ("POSITIVE", "COMB_3") else "DA"
        pdf.cell(W[6], 7, val, 1, 0, "C")
        pdf.set_text_color(0)
    else:
        pdf.cell(W[6], 7, "-", 1, 0, "C")

    if stil:
        pdf.set_text_color(*BOJA_TIP.get(stil["tip"], (0, 0, 0)))
        pdf.cell(W[7], 7, _ascii(f" {stil['oznaka']}", 33), 1, 1, "L")
        pdf.set_text_color(0)
    else:
        pdf.cell(W[7], 7, "", 1, 1)
