from django.db import migrations


def ensure_schedule_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS "Asistent_aischedule" (
                "id" bigserial PRIMARY KEY,
                "name" varchar(200) NOT NULL,
                "strategy_type" varchar(20) NOT NULL DEFAULT 'prompt',
                "strategy_options" jsonb NOT NULL DEFAULT '{}'::jsonb,
                "source_urls" text NOT NULL DEFAULT '',
                "category_id" bigint NULL,
                "tags" varchar(500) NOT NULL DEFAULT '',
                "posting_frequency" varchar(20) NOT NULL DEFAULT 'daily',
                "articles_per_run" integer NOT NULL DEFAULT 1,
                "min_word_count" integer NOT NULL DEFAULT 1000,
                "max_word_count" integer NOT NULL DEFAULT 1500,
                "keywords" text NOT NULL DEFAULT '',
                "tone" varchar(200) NOT NULL DEFAULT 'дружелюбный и экспертный',
                "is_active" boolean NOT NULL DEFAULT TRUE,
                "last_run" timestamptz NULL,
                "next_run" timestamptz NULL,
                "created_at" timestamptz NOT NULL DEFAULT NOW(),
                "updated_at" timestamptz NOT NULL DEFAULT NOW(),
                "video_sources_enabled" boolean NOT NULL DEFAULT FALSE,
                "video_platforms" jsonb NOT NULL DEFAULT '[]'::jsonb,
                "auto_publish_to_platforms" jsonb NOT NULL DEFAULT '[]'::jsonb,
                "video_embed_in_articles" boolean NOT NULL DEFAULT FALSE,
                "telegram_channels" jsonb NOT NULL DEFAULT '[]'::jsonb,
                "rutube_enabled" boolean NOT NULL DEFAULT FALSE,
                "dzen_enabled" boolean NOT NULL DEFAULT FALSE,
                "vk_enabled" boolean NOT NULL DEFAULT FALSE,
                "mimic_author_style_id" bigint NULL,
                "style_strength" integer NOT NULL DEFAULT 5,
                "prompt_template_id" bigint NULL,
                "scheduled_time" time NULL,
                "task_type" varchar(50) NOT NULL DEFAULT 'generate_article',
                "static_params" jsonb NOT NULL DEFAULT '{}'::jsonb,
                "dynamic_params" jsonb NOT NULL DEFAULT '{}'::jsonb,
                "max_runs" integer NULL,
                "current_run_count" integer NOT NULL DEFAULT 0,
                "payload_template" jsonb NOT NULL DEFAULT '{}'::jsonb,
                "schedule_kind" varchar(16) NOT NULL DEFAULT 'daily',
                "cron_expression" varchar(120) NOT NULL DEFAULT '',
                "interval_minutes" integer NULL,
                "weekday" integer NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS "Asistent_aischedulerun" (
                "id" bigserial PRIMARY KEY,
                "schedule_id" bigint NOT NULL,
                "strategy_type" varchar(20) NOT NULL,
                "started_at" timestamptz NOT NULL DEFAULT NOW(),
                "finished_at" timestamptz NULL,
                "status" varchar(20) NOT NULL DEFAULT 'running',
                "created_count" integer NOT NULL DEFAULT 0,
                "errors" jsonb NOT NULL DEFAULT '[]'::jsonb,
                "context_snapshot" jsonb NOT NULL DEFAULT '{}'::jsonb,
                "result_payload" jsonb NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )

        cursor.execute(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'asistent_aischedulerun_schedule_id_fk'
                ) THEN
                    ALTER TABLE "Asistent_aischedulerun"
                    ADD CONSTRAINT asistent_aischedulerun_schedule_id_fk
                    FOREIGN KEY ("schedule_id")
                    REFERENCES "Asistent_aischedule" ("id")
                    ON DELETE CASCADE;
                END IF;
            END$$;
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS "asistent_aischedule_is_active_idx"
            ON "Asistent_aischedule" ("is_active")
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS "asistent_aischedulerun_schedule_id_idx"
            ON "Asistent_aischedulerun" ("schedule_id")
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS "asistent_aischedulerun_started_at_idx"
            ON "Asistent_aischedulerun" ("started_at")
            """
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0002_create_tables_if_missing"),
    ]

    operations = [
        migrations.RunPython(ensure_schedule_tables, noop),
    ]

