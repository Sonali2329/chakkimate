#!/bin/bash
# ==============================================================================
# ChakkiMate (चक्कीमेट) - Database Backup and Restore Utility
# Supports both SQLite and MySQL backups
# ==============================================================================

set -e

BACKUP_DIR="./backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

function show_help() {
    echo "ChakkiMate Database Management Utility"
    echo "Usage: ./backup_restore.sh [backup|restore <backup_file>|status]"
    echo ""
    echo "Commands:"
    echo "  backup               Creates a timestamped snapshot of the current database"
    echo "  restore <file>       Restores the database from a specified backup file"
    echo "  status               Checks database type and existing backups"
}

if [ "$1" == "backup" ]; then
    if [ "$DB_ENGINE" == "mysql" ] || [ -n "$MYSQL_DATABASE" ]; then
        DB_NAME=${MYSQL_DATABASE:-"chakkimate_db"}
        DB_USER=${MYSQL_USER:-"root"}
        DB_HOST=${MYSQL_HOST:-"localhost"}
        TARGET_FILE="$BACKUP_DIR/mysql_${DB_NAME}_${TIMESTAMP}.sql.gz"
        echo "[ChakkiMate] Backing up MySQL database: $DB_NAME..."
        mysqldump -h "$DB_HOST" -u "$DB_USER" "$DB_NAME" | gzip > "$TARGET_FILE"
        echo "[ChakkiMate] Backup created successfully: $TARGET_FILE"
    else
        TARGET_FILE="$BACKUP_DIR/sqlite_db_${TIMESTAMP}.sqlite3"
        echo "[ChakkiMate] Backing up SQLite database..."
        cp db.sqlite3 "$TARGET_FILE"
        echo "[ChakkiMate] Backup created successfully: $TARGET_FILE"
    fi

elif [ "$1" == "restore" ]; then
    if [ -z "$2" ]; then
        echo "Error: Please specify the backup file path to restore."
        exit 1
    fi
    RESTORE_FILE="$2"
    if [ ! -f "$RESTORE_FILE" ]; then
        echo "Error: File $RESTORE_FILE not found!"
        exit 1
    fi

    echo "[ChakkiMate] Restoring database from $RESTORE_FILE..."
    if [[ "$RESTORE_FILE" == *.sqlite3 ]]; then
        cp "$RESTORE_FILE" db.sqlite3
        echo "[ChakkiMate] SQLite restored successfully to db.sqlite3."
    elif [[ "$RESTORE_FILE" == *.sql.gz ]]; then
        DB_NAME=${MYSQL_DATABASE:-"chakkimate_db"}
        DB_USER=${MYSQL_USER:-"root"}
        DB_HOST=${MYSQL_HOST:-"localhost"}
        gunzip < "$RESTORE_FILE" | mysql -h "$DB_HOST" -u "$DB_USER" "$DB_NAME"
        echo "[ChakkiMate] MySQL restored successfully to $DB_NAME."
    else
        echo "Unsupported backup file extension."
    fi

elif [ "$1" == "status" ]; then
    echo "=== ChakkiMate Database Status ==="
    if [ "$DB_ENGINE" == "mysql" ]; then
        echo "Engine: MySQL ($MYSQL_DATABASE on $MYSQL_HOST)"
    else
        echo "Engine: SQLite3 (Local file db.sqlite3)"
    fi
    echo ""
    echo "Available Backups:"
    ls -lh "$BACKUP_DIR" 2>/dev/null || echo "No backups found."
else
    show_help
fi
