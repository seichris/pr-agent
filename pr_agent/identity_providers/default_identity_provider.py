from pr_agent.config_loader import get_settings
from pr_agent.identity_providers.identity_provider import Eligibility, IdentityProvider


def _actor_id(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal():
        return int(value) if int(value) > 0 else None
    return None


class DefaultIdentityProvider(IdentityProvider):
    def verify_eligibility(self, git_provider, git_provider_id, pr_url):
        if git_provider == "github":
            allowed = get_settings().get("GITHUB_APP.ALLOWED_ACTOR_IDS", [])
            if allowed != []:
                # A malformed host policy must never turn into unrestricted access.
                if not isinstance(allowed, (list, tuple)) or not allowed:
                    return Eligibility.NOT_ELIGIBLE
                actor_ids = {_actor_id(value) for value in allowed}
                if None in actor_ids or _actor_id(git_provider_id) not in actor_ids:
                    return Eligibility.NOT_ELIGIBLE
        return Eligibility.ELIGIBLE
