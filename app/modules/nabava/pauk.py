"""Niski nivo - citanje PAUK Excel exporta. Doslovan prijenos iz desktop alata
(Arhiva skripta\\Tjedna usklada\\0.4. Ispravak projekcije i PDF-a\\UskaldaGEN.py) - ovaj
file namjerno ostaje "glup": indeksi stupaca i normalizacija su vec testirani na
stvarnim exportima, pa se ovdje ne prepisuju "slicnim" kodom (tiho bi pukli za dio sifri).
"""
from datetime import datetime

import pandas as pd

# --- Indeksi stupaca u PAUK exportu (0-based), isto kao u desktop alatu ---
C_SIFRA   = 0
C_NAZIV   = 1
C_DOBAV   = 2
C_SKLAD   = 3
C_STANJE  = 11
C_NAK_RN  = 17
C_NAK_NAR = 22
C_ROK     = 42   # rok isporuke radnog naloga U PROIZVODNJU (trosenje)
C_RN      = 43   # broj radnog naloga (za prikaz u tablici dogadjaja)
C_KOL     = 46   # predvideno normativom (trosenje)
C_ZADUZ   = 47   # vec fizicki izdano za radni nalog (trosenje - oduzeti od C_KOL)

# --- Novi indeksi za dolazne narudzbe (Skladiste == "Narudzba"), dosad neiskoristeni ---
C_KOL_NARUDZBA = 34   # narucena kolicina
C_ROK_NARUDZBA = 39   # rok isporuke narudzbe (NAPOMENA: drugi stupac od C_ROK)
C_BR_NARUDZBE  = 37   # broj narudzbe

SKLAD_MAT = "SKLADIŠTE MATERIJALA"
SKLAD_NALOG = {"U tijeku", "Plan"}
SKLAD_NARUDZBA = "Narudžba"

DATE_FMT = "%d.%m.%Y."


def f(val) -> float:
    try:
        v = float(val)
        return v if v == v else 0.0
    except (TypeError, ValueError):
        return 0.0


def izvuci_datum_exporta(df: pd.DataFrame) -> datetime | None:
    """PAUK exportov datum/vrijeme generiranja je upisano u zaglavlje 2. stupca
    (npr. '22.04.2026. 08:26')."""
    try:
        raw = str(df.columns[1]).strip()
        return datetime.strptime(raw, "%d.%m.%Y. %H:%M")
    except (ValueError, TypeError, IndexError):
        return None


def peek_datum(data: bytes) -> datetime | None:
    """Lagano ocitavanje SAMO datuma exporta (cita samo zaglavlje, ne redove) - za brzu
    provjeru 'je li ovaj file vec u arhivi' pri uvozu cijele mape, bez pune obrade."""
    import io
    try:
        df = pd.read_excel(io.BytesIO(data), engine="openpyxl", nrows=0)
        return izvuci_datum_exporta(df)
    except Exception:
        return None


def ucitaj_i_normaliziraj(data: bytes) -> pd.DataFrame:
    """Parsira PAUK export iz bajtova i normalizira sifru/skladiste stupce.
    Excel zna spremiti sifru kao float (npr. '5020103010400001.0') pa se to strippa."""
    import io
    df = pd.read_excel(io.BytesIO(data), engine="openpyxl")
    df.iloc[:, C_SIFRA] = (df.iloc[:, C_SIFRA].astype(str).str.strip()
                            .str.replace(r"\.0$", "", regex=True))
    df.iloc[:, C_SKLAD] = df.iloc[:, C_SKLAD].astype(str).str.strip()
    return df


def sklad_po_sifri(df: pd.DataFrame) -> dict:
    """Red iz SKLADIŠTE MATERIJALA po sifri (prvi pobjeduje ako ima duplikata)."""
    sklad = {}
    for _, red in df[df.iloc[:, C_SKLAD] == SKLAD_MAT].iterrows():
        s = str(red.iloc[C_SIFRA])
        if s not in sklad:
            sklad[s] = red
    return sklad


def df_nalozi(df: pd.DataFrame) -> pd.DataFrame:
    """Retci radnih naloga (trosenje) - Skladiste u {'U tijeku','Plan'}."""
    return df[df.iloc[:, C_SKLAD].isin(SKLAD_NALOG)].copy()


def df_narudzbe(df: pd.DataFrame) -> pd.DataFrame:
    """Retci dolaznih narudzbi (dolazak) - Skladiste == 'Narudžba'."""
    return df[df.iloc[:, C_SKLAD] == SKLAD_NARUDZBA].copy()
