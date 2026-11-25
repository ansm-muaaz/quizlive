-- ============================================================================
-- QuizLive — Supabase Database Setup
-- Run this in the Supabase SQL Editor (or via psql).
-- ============================================================================

-- -------------------------------------------------------------------------
-- 1. TABLES
-- -------------------------------------------------------------------------

-- Profiles (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS public.profiles (
    user_id   UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email     TEXT NOT NULL,
    name      TEXT NOT NULL,
    role      TEXT NOT NULL DEFAULT 'participant'
                   CHECK (role IN ('host', 'participant'))
);

-- Quizzes
CREATE TABLE IF NOT EXISTS public.quizzes (
    id          SERIAL PRIMARY KEY,
    host_id     UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Questions
CREATE TABLE IF NOT EXISTS public.questions (
    id              SERIAL PRIMARY KEY,
    quiz_id         INT NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    question_text   TEXT NOT NULL,
    option_a        TEXT NOT NULL,
    option_b        TEXT NOT NULL,
    option_c        TEXT NOT NULL,
    option_d        TEXT NOT NULL,
    correct_option  CHAR(1) NOT NULL CHECK (correct_option IN ('A','B','C','D')),
    image_url       TEXT,
    time_limit      INT NOT NULL DEFAULT 30
);

-- Results (self-paced quiz attempts)
CREATE TABLE IF NOT EXISTS public.results (
    id           SERIAL PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    quiz_id      INT  NOT NULL REFERENCES public.quizzes(id)  ON DELETE CASCADE,
    score        INT  NOT NULL DEFAULT 0,
    total        INT  NOT NULL DEFAULT 0,
    answers      JSONB DEFAULT '{}'::jsonb,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, quiz_id)
);

-- Game sessions (live mode)
CREATE TABLE IF NOT EXISTS public.game_sessions (
    id                  SERIAL PRIMARY KEY,
    pin                 VARCHAR(6) NOT NULL,
    quiz_id             INT  NOT NULL REFERENCES public.quizzes(id) ON DELETE CASCADE,
    host_id             UUID NOT NULL REFERENCES public.profiles(user_id) ON DELETE CASCADE,
    status              TEXT NOT NULL DEFAULT 'lobby'
                              CHECK (status IN ('lobby','question','reveal','finished')),
    current_question    INT  NOT NULL DEFAULT 0,
    question_started_at TIMESTAMPTZ
);

-- Participants (players in a live game session)
CREATE TABLE IF NOT EXISTS public.participants (
    id         SERIAL PRIMARY KEY,
    session_id INT  NOT NULL REFERENCES public.game_sessions(id) ON DELETE CASCADE,
    user_id    UUID REFERENCES public.profiles(user_id) ON DELETE SET NULL,
    nickname   TEXT NOT NULL,
    score      INT  NOT NULL DEFAULT 0
);

-- Answers (live game answers)
CREATE TABLE IF NOT EXISTS public.answers (
    id             SERIAL PRIMARY KEY,
    participant_id INT  NOT NULL REFERENCES public.participants(id) ON DELETE CASCADE,
    question_id    INT  NOT NULL REFERENCES public.questions(id)    ON DELETE CASCADE,
    choice         CHAR(1) NOT NULL CHECK (choice IN ('A','B','C','D')),
    is_correct     BOOLEAN NOT NULL DEFAULT FALSE,
    points         INT     NOT NULL DEFAULT 0,
    time_taken     NUMERIC(6,2) DEFAULT 0,
    UNIQUE (participant_id, question_id)
);

-- -------------------------------------------------------------------------
-- 2. INDEXES
-- -------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_quizzes_host        ON public.quizzes(host_id);
CREATE INDEX IF NOT EXISTS idx_questions_quiz       ON public.questions(quiz_id);
CREATE INDEX IF NOT EXISTS idx_results_user         ON public.results(user_id);
CREATE INDEX IF NOT EXISTS idx_results_quiz         ON public.results(quiz_id);
CREATE INDEX IF NOT EXISTS idx_game_sessions_pin    ON public.game_sessions(pin);
CREATE INDEX IF NOT EXISTS idx_participants_session ON public.participants(session_id);
CREATE INDEX IF NOT EXISTS idx_answers_participant  ON public.answers(participant_id);
CREATE INDEX IF NOT EXISTS idx_answers_question     ON public.answers(question_id);

-- -------------------------------------------------------------------------
-- 3. ROW LEVEL SECURITY (RLS)
-- -------------------------------------------------------------------------

-- Enable RLS on all tables
ALTER TABLE public.profiles      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.quizzes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.questions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.results       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.game_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.participants  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.answers       ENABLE ROW LEVEL SECURITY;

-- ---- Profiles -----------------------------------------------------------
CREATE POLICY profiles_select ON public.profiles
    FOR SELECT USING (true);  -- anyone can read profiles

CREATE POLICY profiles_insert ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY profiles_update ON public.profiles
    FOR UPDATE USING (auth.uid() = user_id);

-- ---- Quizzes ------------------------------------------------------------
CREATE POLICY quizzes_select ON public.quizzes
    FOR SELECT USING (true);  -- quizzes are publicly browsable

CREATE POLICY quizzes_insert ON public.quizzes
    FOR INSERT WITH CHECK (auth.uid() = host_id);

CREATE POLICY quizzes_update ON public.quizzes
    FOR UPDATE USING (auth.uid() = host_id);

CREATE POLICY quizzes_delete ON public.quizzes
    FOR DELETE USING (auth.uid() = host_id);

-- ---- Questions ----------------------------------------------------------
CREATE POLICY questions_select ON public.questions
    FOR SELECT USING (true);

CREATE POLICY questions_insert ON public.questions
    FOR INSERT WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.quizzes
            WHERE id = quiz_id AND host_id = auth.uid()
        )
    );

CREATE POLICY questions_update ON public.questions
    FOR UPDATE USING (
        EXISTS (
            SELECT 1 FROM public.quizzes
            WHERE id = quiz_id AND host_id = auth.uid()
        )
    );

CREATE POLICY questions_delete ON public.questions
    FOR DELETE USING (
        EXISTS (
            SELECT 1 FROM public.quizzes
            WHERE id = quiz_id AND host_id = auth.uid()
        )
    );

-- ---- Results ------------------------------------------------------------
CREATE POLICY results_select ON public.results
    FOR SELECT USING (
        auth.uid() = user_id
        OR EXISTS (
            SELECT 1 FROM public.quizzes
            WHERE id = quiz_id AND host_id = auth.uid()
        )
    );

CREATE POLICY results_insert ON public.results
    FOR INSERT WITH CHECK (auth.uid() = user_id);

-- ---- Game Sessions ------------------------------------------------------
CREATE POLICY game_sessions_select ON public.game_sessions
    FOR SELECT USING (true);

CREATE POLICY game_sessions_insert ON public.game_sessions
    FOR INSERT WITH CHECK (auth.uid() = host_id);

CREATE POLICY game_sessions_update ON public.game_sessions
    FOR UPDATE USING (auth.uid() = host_id);

-- ---- Participants -------------------------------------------------------
CREATE POLICY participants_select ON public.participants
    FOR SELECT USING (true);

CREATE POLICY participants_insert ON public.participants
    FOR INSERT WITH CHECK (true);  -- guests can join without auth

-- ---- Answers ------------------------------------------------------------
CREATE POLICY answers_select ON public.answers
    FOR SELECT USING (true);

CREATE POLICY answers_insert ON public.answers
    FOR INSERT WITH CHECK (true);  -- guests can answer

-- -------------------------------------------------------------------------
-- 4. STORAGE BUCKET
-- -------------------------------------------------------------------------
-- Run in Supabase SQL editor or create via the Dashboard → Storage UI:
INSERT INTO storage.buckets (id, name, public)
VALUES ('question-images', 'question-images', true)
ON CONFLICT (id) DO NOTHING;

-- Allow authenticated users to upload to the bucket
CREATE POLICY storage_question_images_insert ON storage.objects
    FOR INSERT WITH CHECK (bucket_id = 'question-images' AND auth.role() = 'authenticated');

CREATE POLICY storage_question_images_select ON storage.objects
    FOR SELECT USING (bucket_id = 'question-images');

CREATE POLICY storage_question_images_delete ON storage.objects
    FOR DELETE USING (bucket_id = 'question-images' AND auth.role() = 'authenticated');
