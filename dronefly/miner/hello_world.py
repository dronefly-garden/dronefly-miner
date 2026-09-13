from pyinaturalist import pprint
from pyinaturalist_convert import enable_logging, get_db_taxa, load_dwca_taxa, load_fts_taxa, TaxonAutocompleter

enable_logging()
load_dwca_taxa()
load_fts_taxa(languages=['english', 'german'])
ta = TaxonAutocompleter()
searches = [
    [['aves'], {}],
    [['flughund'], {'language': 'de'}]
]
taxon_ids = []
for args, kwargs in searches:
    mat = ta.search(*args, **kwargs)
    if mat:
        taxon_ids.append(mat[0].id)
for taxon in get_db_taxa(ids=taxon_ids):
    pprint(taxon)
