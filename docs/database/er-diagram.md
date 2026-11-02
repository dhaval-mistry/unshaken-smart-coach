# UNShaken database ER diagram

Design basis: **Reviewed PR #17**, followed by local implementation of stories
#3/#4. See the [detailed design](design.md) and [setup guide](../setup/backend.md).
The model retains 13 tables. The owner's existing database is not migrated.

This diagram shows live foreign keys. Immutable original UUID columns
intentionally are not FKs: source deletion may clear a live link while its
original identity, starting plan, and completed performance remain stored.
Exercise deletion does not cascade into reusable plans; explicit removal/
replacement of live plan references is proposed before catalog deletion.

A unique partial index enforces one in-progress workout per user. Category
measurement_kind and its session snapshot distinguish reps, duration and
duration-plus-distance independently of display labels. Targets, starting
snapshots, and actuals remain separate; weight stays optional.

starting_plan_snapshot is physically nullable only during the creation
transaction. A deferred constraint trigger requires validated non-NULL JSON
at commit; PostgreSQL NOT NULL itself is not deferrable. The populated JSON
is immutable. Removing an unperformed execution set does not erase its initial
plan evidence. Mermaid does not express those JSON, ownership, measurement,
deletion, chronology or immutability guards; the design explains them.

```mermaid
erDiagram
    %% Reviewed PR17 design; local migration implementation, not applied to owner database.
    %% Live FKs may detach after source deletion; original UUID snapshots are not FKs.
    %% starting_plan_snapshot is physically nullable during capture, committed non-NULL by deferred guard.
    %% One in-progress workout/user is enforced by a unique partial index.
    direction TB
    users ||--o{ user_identities : authenticates_with
    users ||--o{ custom_exercises : creates
    users o|--o{ workout_templates : owns
    users ||--o{ workout_sessions : performs
    exercise_categories ||--o{ exercises : categorizes
    body_parts ||--o{ exercises : classifies
    exercises ||--o| provider_exercises : provider_details
    exercises ||--o| custom_exercises : custom_details
    workout_templates ||--o{ template_exercises : contains_live_plan
    exercises ||--o{ template_exercises : requires_live_reference
    template_exercises ||--o{ template_sets : plans
    workout_templates o|--o{ workout_sessions : live_source
    workout_templates o|--o{ workout_sessions : live_applied_target
    workout_templates o|--o{ workout_templates : live_copy_source
    workout_sessions ||--o{ session_exercises : retains
    exercises o|--o{ session_exercises : live_exercise
    template_exercises o|--o{ session_exercises : live_source_entry
    session_exercises ||--o{ session_sets : retains_performance
    template_sets o|--o{ session_sets : live_source_set
    users {
        uuid id PK
        string display_name
        string contact_email
        string preferred_weight_unit
        string status
        timestamptz created_at
        timestamptz updated_at
    }
    user_identities {
        uuid id PK
        uuid user_id FK
        string provider
        text issuer
        text subject
        string email_at_login
        boolean email_verified
        timestamptz last_login_at
        timestamptz created_at
    }
    exercise_categories {
        smallint id PK
        string name
        smallint sort_order
        string measurement_kind
        boolean is_active
    }
    body_parts {
        smallint id PK
        string name
        smallint sort_order
        boolean is_active
    }
    exercises {
        uuid id PK
        string name
        smallint category_id FK
        smallint body_part_id FK
        string source_type
        text description
        boolean is_active
        timestamptz created_at
        timestamptz updated_at
    }
    provider_exercises {
        uuid exercise_id PK,FK
        string provider_name
        text provider_exercise_id
        text provider_body_part
        text provider_equipment
        jsonb instructions
        jsonb target_muscles
        jsonb secondary_muscles
        jsonb media_references
        jsonb raw_payload
        timestamptz last_synced_at
        timestamptz provider_updated_at
    }
    custom_exercises {
        uuid exercise_id PK,FK
        uuid created_by_user_id FK
    }
    workout_templates {
        uuid id PK
        uuid owner_user_id FK
        string template_type
        string name
        text notes
        uuid copied_from_template_id FK
        uuid copied_from_template_id_snapshot
        integer version
        timestamptz archived_at
        timestamptz created_at
        timestamptz updated_at
    }
    template_exercises {
        uuid id PK
        uuid template_id FK
        uuid exercise_id FK
        integer position
        text notes
    }
    template_sets {
        uuid id PK
        uuid template_exercise_id FK
        integer set_number
        integer target_reps
        integer target_duration_seconds
        decimal target_distance_meters
        decimal suggested_weight
        string weight_unit
        integer rest_seconds
    }
    workout_sessions {
        uuid id PK
        uuid user_id FK
        uuid source_template_id FK
        uuid source_template_id_snapshot
        string source_template_type_snapshot
        integer source_template_version
        string name_snapshot
        jsonb starting_plan_snapshot
        string status
        timestamptz started_at
        timestamptz finished_at
        text notes
        timestamptz template_updated_at
        boolean template_update_requested
        string template_update_status
        uuid applied_template_id FK
        uuid applied_template_id_snapshot
        timestamptz created_at
        timestamptz updated_at
    }
    session_exercises {
        uuid id PK
        uuid session_id FK
        uuid exercise_id FK
        uuid exercise_id_snapshot
        string exercise_source_type_snapshot
        uuid source_template_exercise_id FK
        uuid source_template_exercise_id_snapshot
        string name_snapshot
        string category_snapshot
        string body_part_snapshot
        string measurement_kind_snapshot
        integer position
        text notes
    }
    session_sets {
        uuid id PK
        uuid session_exercise_id FK
        uuid source_template_set_id FK
        uuid source_template_set_id_snapshot
        integer set_number
        integer target_reps_snapshot
        integer target_duration_seconds_snapshot
        decimal target_distance_meters_snapshot
        decimal suggested_weight_snapshot
        string suggested_weight_unit_snapshot
        integer actual_reps
        integer actual_duration_seconds
        decimal actual_distance_meters
        decimal actual_weight
        string weight_unit
        string status
        timestamptz completed_at
        integer rest_seconds
        boolean was_in_starting_plan
        timestamptz rest_started_at
        timestamptz rest_ended_at
        timestamptz created_at
        timestamptz updated_at
    }
```

