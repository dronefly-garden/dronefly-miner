import csv
from inspect import signature
import io
import logging
import sqlite3
from pathlib import Path
from platformdirs import user_data_dir
from rich import print
from typing import Optional, Union
from zipfile import ZipFile

from pyinaturalist import pprint
from pyinaturalist_convert import (
    DWCA_TAXA_URL,
    DWCA_URL,
    TaxonAutocompleter,
    create_tables,
    download_file,
    enable_logging,
    get_db_taxa,
    load_dwca_taxa,
    load_fts_taxa,
    aggregate_taxon_db,
)
from pyinaturalist_convert.constants import PathOrStr
from pyinaturalist_convert.download import MultiProgress, check_download, get_progress, _fname, count_lines

USER_DATA_PATH = Path(user_data_dir("dronefly-miner"))
DB_PATH = USER_DATA_PATH / "taxa.db"
DWCA_TAXON_ZIP = USER_DATA_PATH / "inaturalist-taxonomy.dwca.zip"
DWCA_OBS_ZIP = USER_DATA_PATH / "inaturalist-observations.dwca.zip"
DWCA_TAXON_CSV_DIR = USER_DATA_PATH / 'inaturalist-taxonomy.dwca'
DWCA_TAXON_CSV = DWCA_TAXON_CSV_DIR / 'taxa.csv'
DEFAULT_LANG_CSV = DWCA_TAXON_CSV_DIR / 'VernacularNames-english.csv'
TAXON_AGGREGATES_PATH = USER_DATA_PATH / "taxon_aggregates.parquet"
LOAD_CHUNK_SIZE = 50000


logger = logging.getLogger("dronefly.miner")
logger.setLevel(logging.INFO)


class LoadTablesProgress(MultiProgress):
    """Track progress of loading a CSV (line-based) and streaming a Zip (byte-based)"""

    def __init__(self, taxon_csv: PathOrStr, obs_zip: PathOrStr, **kwargs):
        taxon_csv = Path(taxon_csv).expanduser()
        obs_zip = Path(obs_zip).expanduser()

        taxon_name = _fname(taxon_csv)
        taxon_lines = count_lines(taxon_csv) - 1

        obs_name = _fname(obs_zip)
        with ZipFile(obs_zip) as z:
            obs_member = next(m for m in z.infolist() if m.filename.endswith('observations.csv'))
            obs_bytes = obs_member.file_size

        totals = {taxon_name: taxon_lines, obs_name: obs_bytes}

        super().__init__(
            totals=totals,
            total_progress=get_progress(),
            job_progress=get_progress(),
            task_description='Loading',
            **kwargs
        )

        self.total_progress.update(self.total_task, total=200)
        self._current_job_total = 1

    def start_job(self, name: PathOrStr):
        if isinstance(name, Path):
            name = _fname(name)
        self._current_job_total = self.totals[str(name)]
        self.job_progress.update(
            self.job_task,
            completed=0,
            total=self._current_job_total,
        )
        self.job_progress.log(f'[cyan]{self.task_description} [white]{name}[cyan]...')

    def advance(self, advance: int = 1):
        self.job_progress.advance(self.job_task, advance)
        fraction = advance / self._current_job_total
        self.total_progress.advance(self.total_task, fraction * 100)


def load_dwca_observation_counts(
    zip_path: PathOrStr, 
    db_path: PathOrStr, 
    progress: Optional[object] = None
):
    zip_path = Path(zip_path).expanduser()
    db_path = Path(db_path).expanduser()
    
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = MEMORY;")
        conn.execute("PRAGMA synchronous = OFF;")
        conn.execute("PRAGMA temp_store = MEMORY;")
        
        conn.execute("""
            CREATE TABLE IF NOT EXISTS observation (
                taxon_id INTEGER
            );
        """)
        conn.execute("DELETE FROM observation;")
        
        stmt = "INSERT INTO observation (taxon_id) VALUES (?);"
        
        with ZipFile(zip_path, 'r') as z:
            obs_filename = next(f for f in z.namelist() if f.endswith('observations.csv'))
            
            with z.open(obs_filename, 'r') as f:
                text_stream = io.TextIOWrapper(f, encoding='utf-8', newline='')
                reader = csv.DictReader(text_stream)
                
                chunk = []
                for row in reader:
                    taxon_id = row.get('taxonID')
                    if taxon_id:
                        try:
                            chunk.append((int(taxon_id),))
                        except ValueError:
                            continue
                            
                        if len(chunk) >= LOAD_CHUNK_SIZE:
                            conn.executemany(stmt, chunk)
                            if progress and hasattr(progress, 'advance'):
                                progress.advance(sum(len(str(r)) + 2 for r in chunk))
                            chunk.clear()
                            
                if chunk:
                    conn.executemany(stmt, chunk)
                    if progress and hasattr(progress, 'advance'):
                        progress.advance(sum(len(str(r)) + 2 for r in chunk))
                    
        conn.commit()

def load_fts_data(languages: Union[str, list[str]]='all'):
    """Load all full text search data.

    Downloads, builds, and indexes a local database from iNaturalist
    data exported to GBIF as DWCA-A taxonomy and observation data sets,
    supplemented by common names for all languages.
    """
    def _cleanup(staging_db):
        staging_shm = Path(str(staging_db) + "-shm")
        staging_wal = Path(str(staging_db) + "-wal")

        for sidecar in (staging_shm, staging_wal):
            if sidecar.exists():
                sidecar.unlink()

    enable_logging()
    DWCA_TAXON_ZIP.parent.mkdir(parents=True, exist_ok=True)

    taxon_up_to_date = check_download(DWCA_TAXON_ZIP, url=DWCA_TAXA_URL, release_interval=28)
    obs_up_to_date = check_download(DWCA_OBS_ZIP, url=DWCA_URL, release_interval=7)

    if taxon_up_to_date and obs_up_to_date and DB_PATH.exists():
        print("[cyan]Database is fully up to date with upstream archives. Skipping build.")
        return
    print("[cyan]Starting build...")

    if not taxon_up_to_date:
        download_file(DWCA_TAXA_URL, DWCA_TAXON_ZIP)
    if not obs_up_to_date:
        download_file(DWCA_URL, DWCA_OBS_ZIP)

    staging_db = DB_PATH.with_suffix(".db.building")
    if staging_db.exists():
        staging_db.unlink()

    try:
        with LoadTablesProgress(DWCA_TAXON_CSV, DWCA_OBS_ZIP) as progress:
            load_dwca_taxa(csv_path=DWCA_TAXON_CSV, db_path=staging_db, progress=progress)
            load_dwca_observation_counts(zip_path=DWCA_OBS_ZIP, db_path=staging_db, progress=progress)

        aggregate_taxon_db(db_path=staging_db, common_names_path=DEFAULT_LANG_CSV, backup_path=TAXON_AGGREGATES_PATH)
        with sqlite3.connect(staging_db) as conn:
            conn.execute("DROP TABLE IF EXISTS observation;")
            conn.execute("VACUUM;")

        load_fts_taxa(csv_dir=DWCA_TAXON_CSV_DIR, db_path=staging_db, agg_path=TAXON_AGGREGATES_PATH, languages=languages)

        staging_db.replace(DB_PATH)
        _cleanup(staging_db)
        print(f"[green]Successfully updated database: {DB_PATH}")

    except Exception as e:
        print(f"[red]Build failed: {e}")
        if staging_db.exists():
            staging_db.unlink()
            _cleanup(staging_db)
        raise


def taxon_autocomplete(text: str, language=None, rank=None, taxon_id=None, autocompleter: TaxonAutocompleter = None):
    """Autocomplete taxa matching text.

    Autocompletion results are retrieved with a fast lookup against the
    local full-text indexed database.
    """
    global default_taxon_autocompleter

    def hydrate_fts_taxa(fts_taxa):
        fts_taxon_ids = [t.id for t in fts_taxa]
        _db_taxa = [t for t in get_db_taxa(db_path=DB_PATH, ids=fts_taxon_ids)]
        db_taxa = []
        for i, ft_id in enumerate(fts_taxon_ids):
            taxon = next(t for t in _db_taxa if t.id == ft_id)
            taxon.is_active = True
            taxon.matched_term = fts_taxa[i].name
            db_taxa.append(taxon)
        return db_taxa
    _autocompleter = None
    if autocompleter:
        _autocompleter = autocompleter
    else:
        try:
            default_taxon_autocompleter
        except NameError:
            default_taxon_autocompleter = TaxonAutocompleter(db_path=DB_PATH, limit=100)
        _autocompleter = default_taxon_autocompleter

    # TODO: Finish https://github.com/dronefly-garden/pyinaturalist-convert/tree/PR-fts-taxon-rank
    # and submit PR upstream. If taxon_rank is approved and incorporated upstream, bump our dependency
    # to the new version, drop the signature check and warning, and unconditionally supply the parameter.
    kwargs = {"language": language, "taxon_id": taxon_id}
    if "taxon_rank" in signature(_autocompleter.search).parameters:
        kwargs["taxon_rank"] = rank
    else:
        if rank:
            # Not much else we can do here but notify the bot operator, as the
            # help text claims to support rank filtering, but the bot is not using
            # an autocompleter implementation that supports it.
            logger.warning("TaxonAutocompleter.search has no taxon_rank parameter; ignoring: %s", rank)
    fts_taxa = _autocompleter.search(text, **kwargs)

    db_taxa = None
    if fts_taxa:
        db_taxa = hydrate_fts_taxa(fts_taxa)
    return db_taxa

def ta(text: str, language='en'):
    """Do one taxon_autocomplete and pretty-print the top hit.

    A convenience method to play with fta searches.
    """
    db_taxa = taxon_autocomplete(text, language=language)
    if db_taxa:
        print(db_taxa[0].full_name)
        pprint(db_taxa[0])
    else:
        print(f"Not found: {text}")
