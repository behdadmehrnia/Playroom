#!/bin/sh
# Seed + prepare the persistent textbook data volume, then drop to appuser.
set -e

DATA_DIR="${TEXTBOOK_DATA_DIR:-/app/api/textbook/data}"
SEED_DIR="/opt/yarkids/textbook-seed"

mkdir -p "$DATA_DIR/pages" "$DATA_DIR/pdfs"

# First run on an empty named volume: copy catalog metadata from the image.
for f in catalog.json subject_topics.json; do
  if [ ! -f "$DATA_DIR/$f" ] && [ -f "$SEED_DIR/$f" ]; then
    cp "$SEED_DIR/$f" "$DATA_DIR/$f"
  fi
done

chown -R appuser:appuser "$DATA_DIR"

exec runuser -u appuser -- "$@"
