"""Admin registration, for corrections the pages do not offer."""

from django.contrib import admin

from leefanniv.models import BracketMatch, Game, Match, Player, Result, Team, Tournament

admin.site.register([Game, Tournament, Team, Player, Match, Result, BracketMatch])
