--
-- PostgreSQL database dump
--

-- Dumped from database version 12.22
-- Dumped by pg_dump version 14.15 (Homebrew)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: posthog_eventdefinition; Type: TABLE; Schema: public; Owner: posthog
--

CREATE TABLE public.posthog_eventdefinition (
    id uuid NOT NULL,
    name character varying(400) NOT NULL,
    created_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    volume_30_day integer,
    query_usage_30_day integer,
    team_id integer NOT NULL,
    project_id bigint
);


ALTER TABLE public.posthog_eventdefinition OWNER TO posthog;

--
-- Name: posthog_eventdefinition posthog_eventdefinition_pkey; Type: CONSTRAINT; Schema: public; Owner: posthog
--

ALTER TABLE ONLY public.posthog_eventdefinition
    ADD CONSTRAINT posthog_eventdefinition_pkey PRIMARY KEY (id);


--
-- Name: event_definition_proj_uniq; Type: INDEX; Schema: public; Owner: posthog
--

CREATE UNIQUE INDEX event_definition_proj_uniq ON public.posthog_eventdefinition USING btree (COALESCE(project_id, (team_id)::bigint), name);


--
-- Name: index_event_definition_name; Type: INDEX; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): removed "public.*" prefix from gin_trgm_ops and created plugin on DB to support this stmt
--  CREATE EXTENSION IF NOT EXISTS pg_trgm; -- only needs to be done ONCE per DB instance

CREATE INDEX index_event_definition_name ON public.posthog_eventdefinition USING gin (name public.gin_trgm_ops);


--
-- Name: posthog_eve_proj_id_f93fcbb0; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX posthog_eve_proj_id_f93fcbb0 ON public.posthog_eventdefinition USING btree (project_id);


--
-- Name: posthog_eventdefinition_team_id_818ed0f2; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX posthog_eventdefinition_team_id_818ed0f2 ON public.posthog_eventdefinition USING btree (team_id);


--
-- Name: posthog_eventdefinition posthog_eventdefinit_project_id_f93fcbb0_fk_posthog_p; Type: FK CONSTRAINT; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): I DID NOT define this constraint on the new PROPDEFS DB!

ALTER TABLE ONLY public.posthog_eventdefinition
    ADD CONSTRAINT posthog_eventdefinit_project_id_f93fcbb0_fk_posthog_p FOREIGN KEY (project_id) REFERENCES public.posthog_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: posthog_eventdefinition posthog_eventdefinition_team_id_818ed0f2_fk_posthog_team_id; Type: FK CONSTRAINT; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): I DID NOT define this constraint on the new PROPDEFS DB!

ALTER TABLE ONLY public.posthog_eventdefinition
    ADD CONSTRAINT posthog_eventdefinition_team_id_818ed0f2_fk_posthog_team_id FOREIGN KEY (team_id) REFERENCES public.posthog_team(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

