from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from dynaconf import Dynaconf

from pr_agent.algo.cli_args import CliArgs
from pr_agent.config_security import is_repo_host_only_key
from pr_agent.identity_providers import default_identity_provider as module
from pr_agent.identity_providers.identity_provider import Eligibility


@pytest.mark.parametrize("sender", [123, "123", "00123"])
@pytest.mark.parametrize("allowed", [[123], ["123"], [456, "123"]])
def test_allowed_immutable_actor_id_is_eligible(monkeypatch, sender, allowed):
    settings = Dynaconf(github_app={"allowed_actor_ids": allowed}, core_loaders=[], loaders=[])
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert module.DefaultIdentityProvider().verify_eligibility("github", sender, "unused") is Eligibility.ELIGIBLE


@pytest.mark.parametrize("sender", [None, "", 456, "seichris", True, 123.0, "１２３"])
def test_missing_or_unlisted_actor_is_denied(monkeypatch, sender):
    settings = Dynaconf(github_app={"allowed_actor_ids": [123]}, core_loaders=[], loaders=[])
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert module.DefaultIdentityProvider().verify_eligibility("github", sender, "unused") is Eligibility.NOT_ELIGIBLE


@pytest.mark.parametrize(
    "allowed", [None, "123", 123, True, {}, ["invalid"], ["1" * 5000], [123, None], [True], [0], [-1]]
)
def test_malformed_host_policy_fails_closed(monkeypatch, allowed):
    settings = Dynaconf(github_app={"allowed_actor_ids": allowed}, core_loaders=[], loaders=[])
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    assert module.DefaultIdentityProvider().verify_eligibility("github", 123, "unused") is Eligibility.NOT_ELIGIBLE


def test_unconfigured_policy_and_other_providers_retain_behavior(monkeypatch):
    settings = Dynaconf(github_app={"allowed_actor_ids": []}, core_loaders=[], loaders=[])
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    provider = module.DefaultIdentityProvider()
    assert provider.verify_eligibility("github", None, "unused") is Eligibility.ELIGIBLE
    settings.set("github_app.allowed_actor_ids", [123])
    assert provider.verify_eligibility("gitlab", 456, "unused") is Eligibility.ELIGIBLE


@pytest.mark.parametrize("arg", ["github_app.allowed_actor_ids", "GITHUB_APP.ALLOWED_ACTOR_IDS"])
def test_comment_arguments_cannot_disable_actor_authorization(arg):
    assert is_repo_host_only_key("github_app", "allowed_actor_ids")
    assert CliArgs.validate_user_args([f"--{arg}=[]"])[0] is False


@pytest.mark.parametrize("sender_id,expected_calls", [(123, 1), (456, 0), (None, 0)])
@pytest.mark.parametrize("trigger", ["comment", "opened", "review"])
async def test_webhook_dispatch_checks_actual_actor_before_model_dispatch(
    monkeypatch, sender_id, expected_calls, trigger
):
    from pr_agent.servers import github_app

    settings = Dynaconf(
        github_app={"allowed_actor_ids": [123], "handle_pr_actions": ["opened"]}, core_loaders=[], loaders=[]
    )
    monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(github_app, "get_settings", lambda: settings)
    monkeypatch.setattr(github_app, "get_identity_provider", module.DefaultIdentityProvider)
    monkeypatch.setattr(github_app, "apply_repo_settings", lambda _: None)
    url = "https://api.github.com/repos/owner/repo/pulls/1"
    body = {"pull_request": {"draft": False}, "review": {"state": "changes_requested", "user": {"type": "User"}}}
    monkeypatch.setattr(github_app, "_check_pull_request_event", lambda *args: (body["pull_request"], url))
    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(github_app, "_perform_auto_commands_github", dispatch)
    provider = SimpleNamespace(add_eyes_reaction=Mock(), react_to_outcome=Mock())
    monkeypatch.setattr(github_app, "get_git_provider_with_context", lambda **_: provider)
    agent = SimpleNamespace(handle_request=dispatch)
    if trigger == "comment":
        body.update({"comment": {"id": 1, "body": "/review"}, "issue": {"pull_request": {"url": url}}})
        await github_app.handle_comments_on_pr(body, "issue_comment", "actor", sender_id, "created", {}, agent)
    elif trigger == "opened":
        await github_app.handle_new_pr_opened(body, "pull_request", "actor", sender_id, "opened", {}, agent)
    else:
        await github_app.handle_pull_request_review_submitted(
            body, "pull_request_review", "actor", sender_id, "User", "submitted", {}, agent
        )
    assert dispatch.await_count == expected_calls
