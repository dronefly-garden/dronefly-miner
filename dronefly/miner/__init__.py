from inspect import signature
import logging
from platformdirs import user_data_dir
import os

from pyinaturalist import pprint
from pyinaturalist_convert import enable_logging, get_db_taxa, load_dwca_tables, load_fts_taxa, aggregate_taxon_db, TaxonAutocompleter

USER_DATA_PATH = os.path.join(user_data_dir(), "dronefly-miner")
DB_PATH = os.path.join(USER_DATA_PATH, 'observations.db')

logger = logging.getLogger("dronefly.miner")
logger.setLevel(logging.INFO)

def load_fts_data():
    """Load all full text search data.

    Downloads, builds, and indexes a local database from iNaturalist
    data exported to GBIF as DWCA-A taxonomy and observation data sets,
    supplemented by common names for all languages.
    """
    enable_logging()
    load_dwca_tables(db_path=DB_PATH)
    aggregate_taxon_db(db_path=DB_PATH)
    load_fts_taxa(db_path=DB_PATH, languages='all')

def taxon_autocomplete(text: str, language='en', rank=None, autocompleter: TaxonAutocompleter = None):
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
            default_taxon_autocompleter = TaxonAutocompleter(db_path=DB_PATH, limit=10)
        _autocompleter = default_taxon_autocompleter

    # TODO: Finish https://github.com/dronefly-garden/pyinaturalist-convert/tree/PR-fts-taxon-rank
    # and submit PR upstream. If taxon_rank is approved and incorporated upstream, bump our dependency
    # to the new version, drop the signature check and warning, and unconditionally supply the parameter.
    kwargs = {"language": language}
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
