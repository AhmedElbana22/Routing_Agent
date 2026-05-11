FROM postgis/postgis:18-3.6

# Install required PostgreSQL extensions
RUN apt-get update && apt-get install -y \
    postgresql-contrib \
    postgis \
    postgresql-18-postgis-3 \
    postgresql-18-pgrouting \
    uuid-runtime \
    && rm -rf /var/lib/apt/lists/*

# Create initialization directory
RUN mkdir -p /docker-entrypoint-initdb.d

# Copy SQL schemas
COPY sql/schema.sql /docker-entrypoint-initdb.d/02-schema.sql
COPY sql/gtfs-staging-schema.sql /docker-entrypoint-initdb.d/03-gtfs-staging-schema.sql
COPY sql/gtfs-etl-transform.sql /docker-entrypoint-initdb.d/04-gtfs-etl-transform.sql

# Copy initialization scripts
COPY scripts/init-database.sh /docker-entrypoint-initdb.d/01-init-database.sh
COPY scripts/init-gtfs.sh /docker-entrypoint-initdb.d/05-init-gtfs.sh

# Copy common database connection setup and GTFS management scripts
COPY scripts/common.sh /usr/local/bin/common.sh
COPY scripts/gtfs2db.sh /usr/local/bin/gtfs2db.sh
COPY scripts/gtfs-etl.sh /usr/local/bin/gtfs-etl.sh

# Copy GTFS data
COPY gtfs-data /gtfs-data

# Make all scripts executable
RUN chmod +x /docker-entrypoint-initdb.d/*.sh \
    && chmod +x /usr/local/bin/*.sh

# Set environment variables
ENV POSTGRES_DB=transport_db
ENV POSTGRES_USER=postgres
ENV POSTGRES_PASSWORD=postgres

EXPOSE 5432

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["postgres"]