"""The app's templates must be the ones Django finds.

They used to live in a project-level `templates/` directory, which
`TEMPLATES["DIRS"]` searches ahead of every installed app. That hid an
ordering question completely: it did not matter where `directory` sat in
INSTALLED_APPS, because DIRS won regardless.

They now live inside the app, so it can be installed elsewhere and bring
them along. That makes the ordering load-bearing. `APP_DIRS` walks
INSTALLED_APPS and takes the first match, so `directory` has to precede
`django.contrib.admin` and `allauth.account` or its admin chrome and its
sign-in page are silently replaced by the stock ones — no error, just
the wrong page.

These are the tests that fail when someone tidies INSTALLED_APPS into
alphabetical order.
"""

from django.conf import settings
from django.template.loader import get_template


def _origin(name):
    return get_template(name).origin.name


def test_the_app_comes_before_what_it_overrides():
    apps = list(settings.INSTALLED_APPS)
    assert apps.index("directory") < apps.index("django.contrib.admin")
    assert apps.index("directory") < apps.index("allauth.account")


def test_no_project_level_template_directory():
    """A DIRS entry would mask the ordering again, and would not travel
    with the app when it is installed as a package."""
    assert settings.TEMPLATES[0]["DIRS"] == []
    assert settings.TEMPLATES[0]["APP_DIRS"] is True


def test_the_admin_chrome_resolves_to_this_app():
    for name in ("admin/base_site.html", "admin/index.html"):
        assert "/directory/templates/" in _origin(name), name


def test_the_sign_in_page_resolves_to_this_app():
    """Not allauth's. allauth ships its own account/login.html and is
    installed after this app precisely so ours wins."""
    for name in ("account/login.html", "account/signup.html", "base_auth.html"):
        assert "/directory/templates/" in _origin(name), name


def test_the_templates_are_inside_the_package():
    """What a wheel ships is what sits inside the package directory."""
    from pathlib import Path

    import directory

    root = Path(directory.__file__).parent / "templates"
    assert root.is_dir()
    shipped = {str(p.relative_to(root)) for p in root.rglob("*.html")}
    assert shipped == {
        "base_auth.html",
        "account/login.html",
        "account/no_access.html",
        "account/signup.html",
        "admin/base_site.html",
        "admin/index.html",
    }


# --- what a wheel would contain ---------------------------------------------


def _pyproject():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    return tomllib.loads((root / "pyproject.toml").read_text())


def test_the_app_is_buildable_as_a_distribution():
    """Another Django project installs this and adds `directory` to its
    INSTALLED_APPS. Without a build backend there is nothing to install."""
    assert _pyproject()["build-system"]["build-backend"] == "setuptools.build_meta"


def test_the_project_package_is_not_shipped():
    """`config` is settings, urls and wsgi — this repository's own
    service. A consuming project supplies its own, and shipping ours
    would put a second settings module on its path."""
    include = _pyproject()["tool"]["setuptools"]["packages"]["find"]["include"]
    assert sorted(include) == ["checks*", "directory*", "feed*"]
    assert not any(i.startswith("config") for i in include)


def test_the_templates_are_declared_as_package_data():
    """Python packaging ships .py files and nothing else unless told.
    Without this the app installs and every page 500s on a missing
    template."""
    data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert data["directory"] == ["templates/**/*.html"]


def test_the_dependencies_are_the_apps_not_the_deployments():
    """gunicorn, whitenoise, psycopg and dj-database-url serve this
    repository's service; a project installing the app brings its own.
    pandas and openpyxl are tooling — nothing in directory, checks or
    feed imports them, and pulling them into a consumer would be rude."""
    deps = " ".join(_pyproject()["project"]["dependencies"])
    for wanted in ("Django", "allauth", "import-export", "simple-history"):
        assert wanted in deps, wanted
    for unwanted in ("gunicorn", "whitenoise", "psycopg", "dj-database-url", "pandas", "openpyxl"):
        assert unwanted not in deps, unwanted
