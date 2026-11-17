import json
from pathlib import Path
from jobmatcher_resume.models import CandidateExtractionResult
Path('schemas/candidate-profile.schema.json').write_text(json.dumps(CandidateExtractionResult.model_json_schema(),indent=2),encoding='utf-8')
