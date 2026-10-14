-- 001_foundations: accounts, roles, parent/child profiles, teachers, Quran text.
--
-- Migrations are plain SQL files applied in filename order by `python -m app.cli migrate`.
-- Never edit a migration that has already been applied to a live database; add a new file.

-- ---------------------------------------------------------------------------
-- Accounts
-- ---------------------------------------------------------------------------

CREATE TABLE users (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Adults sign in with email and password. Child profiles have neither:
    -- they are opened by a parent from the parent's own account.
    email          text UNIQUE,
    password_hash  text,
    display_name   text NOT NULL,
    language       text NOT NULL DEFAULT 'ar',
    timezone       text NOT NULL DEFAULT 'UTC',
    is_child       boolean NOT NULL DEFAULT false,
    is_active      boolean NOT NULL DEFAULT true,
    failed_logins  integer NOT NULL DEFAULT 0,
    locked_until   timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT users_display_name_length CHECK (char_length(display_name) BETWEEN 1 AND 80),
    CONSTRAINT users_language_supported  CHECK (language IN ('ar', 'en', 'fr')),
    CONSTRAINT users_email_lowercase     CHECK (email IS NULL OR email = lower(email)),
    CONSTRAINT users_child_has_no_login  CHECK (is_child = (email IS NULL)),
    CONSTRAINT users_login_is_complete   CHECK ((email IS NULL) = (password_hash IS NULL))
);

CREATE TABLE user_roles (
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    role        text NOT NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (user_id, role),
    CONSTRAINT user_roles_known_role CHECK (role IN ('student', 'parent', 'teacher', 'admin'))
);

-- A child profile may only ever be a student.
CREATE FUNCTION guard_child_roles() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.role <> 'student'
       AND EXISTS (SELECT 1 FROM users WHERE id = NEW.user_id AND is_child) THEN
        RAISE EXCEPTION 'A child profile can only have the student role.'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER user_roles_child_guard
    BEFORE INSERT OR UPDATE ON user_roles
    FOR EACH ROW EXECUTE FUNCTION guard_child_roles();

-- Links a parent account to a child profile, with the date consent was given.
CREATE TABLE guardian_links (
    guardian_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    child_id          uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    consent_given_at  timestamptz NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (guardian_id, child_id),
    CONSTRAINT guardian_links_not_self CHECK (guardian_id <> child_id)
);

CREATE INDEX guardian_links_child ON guardian_links (child_id);

-- Long-lived sign-in tokens. Only a SHA-256 hash is stored, never the token.
CREATE TABLE refresh_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    revoked_at  timestamptz,
    -- True when the token was retired by being exchanged for a newer one.
    -- Seeing such a token again means it was copied, so the account is signed out.
    was_rotated boolean NOT NULL DEFAULT false
);

CREATE INDEX refresh_tokens_user ON refresh_tokens (user_id);

-- ---------------------------------------------------------------------------
-- Riwayat and the Quran text
-- ---------------------------------------------------------------------------

CREATE TABLE riwayat (
    code           text PRIMARY KEY,
    name_ar        text NOT NULL,
    name_en        text NOT NULL,
    name_fr        text NOT NULL,
    sort_order     integer NOT NULL,
    -- empty: no text loaded. imported: text loaded, waiting for a qualified
    -- reviewer. approved: signed off and visible to everyone.
    status         text NOT NULL DEFAULT 'empty',
    ayah_count     integer,
    text_source    text,
    text_notice    text,
    file_sha256    text,
    content_sha256 text,
    imported_at    timestamptz,
    reviewer_name  text,
    approved_by    uuid REFERENCES users (id) ON DELETE SET NULL,
    approved_at    timestamptz,

    CONSTRAINT riwayat_known_status CHECK (status IN ('empty', 'imported', 'approved')),
    CONSTRAINT riwayat_empty_has_no_text
        CHECK ((status = 'empty') = (imported_at IS NULL)),
    CONSTRAINT riwayat_approval_is_complete
        CHECK ((status = 'approved') = (approved_at IS NOT NULL AND reviewer_name IS NOT NULL))
);

INSERT INTO riwayat (code, name_ar, name_en, name_fr, sort_order) VALUES
    ('hafs',  'حفص عن عاصم', 'Hafs from Asim', 'Hafs d''après Asim', 1),
    ('warsh', 'ورش عن نافع', 'Warsh from Nafi', 'Warsh d''après Nafi', 2);

CREATE TABLE ayahs (
    riwaya_code   text     NOT NULL REFERENCES riwayat (code),
    surah_number  smallint NOT NULL,
    ayah_number   smallint NOT NULL,
    text          text     NOT NULL,

    PRIMARY KEY (riwaya_code, surah_number, ayah_number),
    CONSTRAINT ayahs_surah_range  CHECK (surah_number BETWEEN 1 AND 114),
    CONSTRAINT ayahs_ayah_positive CHECK (ayah_number >= 1),
    CONSTRAINT ayahs_text_present CHECK (text <> '')
);

-- The Quran text is read-only. Only the import command, which switches on
-- the setting below for its own transaction, may write to this table.
CREATE FUNCTION guard_quran_text() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF coalesce(current_setting('tajweed.quran_import', true), '') <> 'on' THEN
        RAISE EXCEPTION 'The Quran text is read-only. Use the import command to load or replace it.'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_LEVEL = 'STATEMENT' THEN
        RETURN NULL;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER ayahs_guard_rows
    BEFORE INSERT OR UPDATE OR DELETE ON ayahs
    FOR EACH ROW EXECUTE FUNCTION guard_quran_text();

CREATE TRIGGER ayahs_guard_truncate
    BEFORE TRUNCATE ON ayahs
    FOR EACH STATEMENT EXECUTE FUNCTION guard_quran_text();

-- ---------------------------------------------------------------------------
-- Teachers (hired staff, created by an admin)
-- ---------------------------------------------------------------------------

CREATE TABLE teacher_profiles (
    user_id      uuid PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    gender       text NOT NULL,
    credentials  text NOT NULL DEFAULT '',
    is_verified  boolean NOT NULL DEFAULT false,
    verified_by  uuid REFERENCES users (id) ON DELETE SET NULL,
    verified_at  timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT teacher_profiles_gender CHECK (gender IN ('male', 'female')),
    CONSTRAINT teacher_profiles_verification_is_complete
        CHECK (is_verified = (verified_at IS NOT NULL))
);

CREATE TABLE teacher_riwayat (
    user_id      uuid NOT NULL REFERENCES teacher_profiles (user_id) ON DELETE CASCADE,
    riwaya_code  text NOT NULL REFERENCES riwayat (code),
    PRIMARY KEY (user_id, riwaya_code)
);

CREATE TABLE teacher_languages (
    user_id   uuid NOT NULL REFERENCES teacher_profiles (user_id) ON DELETE CASCADE,
    language  text NOT NULL,
    PRIMARY KEY (user_id, language),
    CONSTRAINT teacher_languages_supported CHECK (language IN ('ar', 'en', 'fr'))
);

-- ---------------------------------------------------------------------------
-- Record of what admins did, and to whom
-- ---------------------------------------------------------------------------

CREATE TABLE admin_actions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id        uuid NOT NULL REFERENCES users (id),
    action          text NOT NULL,
    target_user_id  uuid REFERENCES users (id) ON DELETE SET NULL,
    detail          text NOT NULL DEFAULT '',
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX admin_actions_created ON admin_actions (created_at DESC);
