from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.models.theme import Theme
from app.models.template import Template
from app.models.presentation import Presentation
from app.models.generation_job import GenerationJob
from app.models.export_job import ExportJob

ALL_MODELS = [User, RefreshToken, Theme, Template, Presentation, GenerationJob, ExportJob]
