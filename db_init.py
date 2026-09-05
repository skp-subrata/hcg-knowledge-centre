"""Apply the SQL init scripts in init_scripts/ to the LMS database.

Each ``init_scripts/*.sql`` file is applied once per database, in filename
order, and recorded in the ``schema_migrations`` table. ``app.init_db()`` calls
:func:`apply_init_scripts` on every start-up, so a fresh database is fully
created the first time the app runs and an existing one is upgraded in place.

To add a change: drop a new ``NNN_description.sql`` into ``init_scripts/``
using ``CREATE TABLE IF NOT EXISTS`` / ``INSERT OR IGNORE``. ``ALTER TABLE ...
ADD COLUMN`` is also safe: a column that already exists is skipped.

Run standalone with ``python db_init.py`` or ``flask --app app init-db``.
"""
import sqlite3
from pathlib import Path

INIT_SCRIPTS_DIR = Path(__file__).with_name("init_scripts")


def _has_sql(text):
	"""True if *text* contains something other than blank lines and -- comments."""
	return any(line.strip() and not line.strip().startswith("--") for line in text.splitlines())


def _statements(sql):
	"""Split a script into complete statements (semicolons inside strings/comments are safe)."""
	buffer = []
	for line in sql.splitlines(keepends=True):
		buffer.append(line)
		candidate = "".join(buffer)
		if sqlite3.complete_statement(candidate):
			buffer = []
			if _has_sql(candidate):
				yield candidate.strip()
	tail = "".join(buffer)
	if _has_sql(tail):
		yield tail.strip()


def apply_init_scripts(connection, scripts_dir=INIT_SCRIPTS_DIR):
	"""Apply every not-yet-applied script in *scripts_dir*; return the names applied now."""
	connection.execute(
		"""CREATE TABLE IF NOT EXISTS schema_migrations (
			name TEXT PRIMARY KEY,
			applied_at TEXT DEFAULT CURRENT_TIMESTAMP
		)"""
	)
	already = {row[0] for row in connection.execute("SELECT name FROM schema_migrations")}
	applied_now = []
	for script in sorted(Path(scripts_dir).glob("*.sql")):
		if script.name in already:
			continue
		for statement in _statements(script.read_text(encoding="utf-8")):
			try:
				connection.execute(statement)
			except sqlite3.OperationalError as exc:
				is_add_column = "add column" in statement.lower()
				if is_add_column and "duplicate column name" in str(exc).lower():
					continue  # column exists already (database predates this script)
				raise RuntimeError(f"init script {script.name} failed: {exc}\n{statement}") from exc
		connection.execute("INSERT INTO schema_migrations (name) VALUES (?)", (script.name,))
		applied_now.append(script.name)
	connection.commit()
	return applied_now


def applied_scripts(connection):
	"""Return [(name, applied_at), ...] for every script recorded in schema_migrations."""
	return [
		(row[0], row[1])
		for row in connection.execute("SELECT name, applied_at FROM schema_migrations ORDER BY name")
	]


def main():
	# Importing app builds the Flask app, which runs init_db() -> apply_init_scripts().
	import app as lms

	with lms.get_db() as connection:
		rows = applied_scripts(connection)
	print(f"Database ready: {lms.DATABASE}")
	for name, applied_at in rows:
		print(f"  init script {name} (applied {applied_at})")


if __name__ == "__main__":
	main()
