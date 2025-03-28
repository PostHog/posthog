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
-- Name: posthog_propertydefinition; Type: TABLE; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): may be cheaper to enforce some of these CONSTRAINTs in code; the service + API default group type index to -1 if it should be NULL anyway (etc.)

CREATE TABLE public.posthog_propertydefinition (
    id uuid NOT NULL,
    name character varying(400) NOT NULL,
    is_numerical boolean NOT NULL,
    query_usage_30_day integer,
    property_type character varying(50),
    property_type_format character varying(50),
    volume_30_day integer,
    team_id integer NOT NULL,
    group_type_index smallint,
    type smallint DEFAULT 1 NOT NULL,
    project_id bigint,
    CONSTRAINT group_type_index_set CHECK (((NOT (type = 3)) OR (group_type_index IS NOT NULL))),
    CONSTRAINT posthog_propertydefinition_group_type_index_check CHECK ((group_type_index >= 0)),
    CONSTRAINT posthog_propertydefinition_type_check CHECK ((type >= 0))
);


ALTER TABLE public.posthog_propertydefinition OWNER TO posthog;

--
-- Name: posthog_propertydefinition posthog_propertydefinition_pkey; Type: CONSTRAINT; Schema: public; Owner: posthog
--

ALTER TABLE ONLY public.posthog_propertydefinition
    ADD CONSTRAINT posthog_propertydefinition_pkey PRIMARY KEY (id);


--
-- Name: posthog_propertydefinition property_type_is_valid; Type: CHECK CONSTRAINT; Schema: public; Owner: posthog
--

ALTER TABLE public.posthog_propertydefinition
    ADD CONSTRAINT property_type_is_valid CHECK (((property_type)::text = ANY ((ARRAY['DateTime'::character varying, 'String'::character varying, 'Numeric'::character varying, 'Boolean'::character varying, 'Duration'::character varying])::text[]))) NOT VALID;


--
-- Name: index_property_def_query; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX index_property_def_query ON public.posthog_propertydefinition USING btree (team_id, type, COALESCE((group_type_index)::integer, '-1'::integer), query_usage_30_day DESC NULLS LAST, name);


--
-- Name: index_property_def_query_proj; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX index_property_def_query_proj ON public.posthog_propertydefinition USING btree (COALESCE(project_id, (team_id)::bigint), type, COALESCE((group_type_index)::integer, '-1'::integer), query_usage_30_day DESC NULLS LAST, name);

--
-- Name: index_property_definition_name; Type: INDEX; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): removed "public.*" prefix from gin_trgm_ops and created plugin on DB to support this stmt
--  CREATE EXTENSION IF NOT EXISTS pg_trgm; -- only needs to be done ONCE per DB instance

CREATE INDEX index_property_definition_name ON public.posthog_propertydefinition USING gin (name public.gin_trgm_ops);


--
-- Name: posthog_pro_project_3583d2_idx; Type: INDEX; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): we can probably ditch this in favor of posthog_pro_team_id_eac36d_idx soon (cc @BenWhite)

CREATE INDEX posthog_pro_project_3583d2_idx ON public.posthog_propertydefinition USING btree (COALESCE(project_id, (team_id)::bigint), type, is_numerical);


--
-- Name: posthog_pro_team_id_eac36d_idx; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX posthog_pro_team_id_eac36d_idx ON public.posthog_propertydefinition USING btree (team_id, type, is_numerical);


--
-- Name: posthog_prop_proj_id_d3eb982d; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX posthog_prop_proj_id_d3eb982d ON public.posthog_propertydefinition USING btree (project_id);


--
-- Name: posthog_propdef_proj_uniq; Type: INDEX; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): this could be troublesome and will need replacement (?) once we ditch project_id (cc @BenWhite)

CREATE UNIQUE INDEX posthog_propdef_proj_uniq ON public.posthog_propertydefinition USING btree (COALESCE(project_id, (team_id)::bigint), name, type, COALESCE((group_type_index)::integer, '-1'::integer));


--
-- Name: posthog_propertydefinition_team_id_b7abe702; Type: INDEX; Schema: public; Owner: posthog
--

CREATE INDEX posthog_propertydefinition_team_id_b7abe702 ON public.posthog_propertydefinition USING btree (team_id);


--
-- Name: posthog_propertydefinition posthog_propertydefi_project_id_d3eb982d_fk_posthog_p; Type: FK CONSTRAINT; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): I DID NOT create this constraint on the new PROPDEFS DB

ALTER TABLE ONLY public.posthog_propertydefinition
    ADD CONSTRAINT posthog_propertydefi_project_id_d3eb982d_fk_posthog_p FOREIGN KEY (project_id) REFERENCES public.posthog_project(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: posthog_propertydefinition posthog_propertydefinition_team_id_b7abe702_fk_posthog_team_id; Type: FK CONSTRAINT; Schema: public; Owner: posthog
--

-- IMPORTANT(eli.r): I DID NOT create this constraint on the new PROPDEFS DB

ALTER TABLE ONLY public.posthog_propertydefinition
    ADD CONSTRAINT posthog_propertydefinition_team_id_b7abe702_fk_posthog_team_id FOREIGN KEY (team_id) REFERENCES public.posthog_team(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

