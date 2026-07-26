#!/bin/sh
# Prepare the persistent textbook data volume, then drop to appuser.
#
# The named volume keeps heavy runtime data (pages/, pdfs/, index.sqlite).
# Structure maps (catalog.json, subject_topics.json) always come from the
# image seed so rebuilds pick up TOC updates — otherwise an old volume hides
# the new catalog and outline/lesson lookup silently returns lesson_missing.
set -e

DATA_DIR="${TEXTBOOK_DATA_DIR:-/app/api/textbook/data}"
SEED_DIR="/opt/yarkids/textbook-seed"

mkdir -p "$DATA_DIR/pages" "$DATA_DIR/pdfs"

for f in catalog.json subject_topics.json; do
  if [ -f "$SEED_DIR/$f" ]; then
    cp "$SEED_DIR/$f" "$DATA_DIR/$f"
  fi
done

chown -R appuser:appuser "$DATA_DIR"

exec runuser -u appuser -- "$@"
