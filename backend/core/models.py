"""
Tabilo — Phase 1 Core Models

Unified multi-tenant "basement" schema serving both School Edition
(weekly Mon-Sat schedules) and College Edition (rolling Day 1-6 order
rotations) from a single set of tables.

Design notes:
- Every tenant-scoped model carries a direct `institution` FK (not just a
  transitive one through a parent) so tenant-isolation filters and indexes
  stay cheap and explicit at every table, per the strict multi-tenancy
  requirement.
- `Institution.cycle_length` + `TimeSlot.day_identifier` is the single
  abstraction that covers both School (weekday 1-6 = Mon-Sat) and College
  (Day-Order 1-6) without maintaining two parallel calendar schemas.
- Hard constraints (no teacher double-booking, no class double-booking) are
  enforced at the database level on TimetableCell via unique_together, not
  left to application code.
- Elective parallelism is modeled via ElectiveGroup: multiple
  CourseRequirement rows (possibly from different departments/class
  divisions) can share a group, and the Phase 3 solver is responsible for
  placing every requirement in a group into the same TimeSlot.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q, F


# ---------------------------------------------------------------------------
# Tenant root
# ---------------------------------------------------------------------------

class Institution(models.Model):
    SCHOOL = "SCHOOL"
    COLLEGE = "COLLEGE"
    INSTITUTION_TYPE_CHOICES = [
        (SCHOOL, "School"),
        (COLLEGE, "College"),
    ]

    name = models.CharField(max_length=255)
    institution_type = models.CharField(max_length=10, choices=INSTITUTION_TYPE_CHOICES)

    # Length of the rotation cycle: 5/6 for a School's Mon-Fri/Sat week,
    # 6 for a College's Day 1-6 order. This single field is what lets
    # TimeSlot stay generic across both editions.
    cycle_length = models.PositiveSmallIntegerField(default=6)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.institution_type})"


# ---------------------------------------------------------------------------
# Organizational structure
# ---------------------------------------------------------------------------

class Department(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="departments")
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["institution", "name"]
        unique_together = ("institution", "name")
        indexes = [models.Index(fields=["institution", "name"])]

    def __str__(self):
        return f"{self.name} ({self.institution.name})"


class AcademicTerm(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="academic_terms")
    name = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        unique_together = ("institution", "name")
        indexes = [models.Index(fields=["institution", "is_active"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="term_end_after_start",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.institution.name})"


# ---------------------------------------------------------------------------
# People & offerings
# ---------------------------------------------------------------------------

class Teacher(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="teachers")
    name = models.CharField(max_length=255)
    email = models.EmailField()

    # Hard workload caps (e.g. Anna University Asst. Professors: 24 hrs/week).
    max_periods_per_day = models.PositiveSmallIntegerField()
    max_periods_per_week = models.PositiveSmallIntegerField()

    is_active = models.BooleanField(default=True)  # False once resigned/exited

    class Meta:
        ordering = ["institution", "name"]
        unique_together = ("institution", "email")
        indexes = [models.Index(fields=["institution", "is_active"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(max_periods_per_day__gt=0) & Q(max_periods_per_week__gt=0),
                name="teacher_caps_positive",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.institution.name})"


class Subject(models.Model):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    COGNITIVE_LOAD_CHOICES = [
        (HIGH, "High"),
        (NORMAL, "Normal"),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="subjects")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32)
    is_elective = models.BooleanField(default=False)

    # Phase 3b: subjects that deserve a "fresh mind" placement (e.g. a hard
    # Math period) get scheduled preferentially in the first half of the day
    # when cognitive_load_weight favors it — see core/solver/build.py.
    cognitive_load_priority = models.CharField(
        max_length=10, choices=COGNITIVE_LOAD_CHOICES, default=NORMAL
    )

    class Meta:
        ordering = ["institution", "department", "name"]
        unique_together = ("institution", "code")
        indexes = [
            models.Index(fields=["institution", "department"]),
            models.Index(fields=["institution", "is_elective"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class TeacherSubjectEligibility(models.Model):
    """
    Which teachers are qualified to teach which subjects. Consulted by the
    Phase 3 solver only for CourseRequirements with no pre-assigned teacher.
    """
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="subject_eligibilities")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="subject_eligibilities")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="eligible_teachers")

    class Meta:
        ordering = ["institution", "teacher", "subject"]
        unique_together = ("teacher", "subject")
        indexes = [
            models.Index(fields=["institution", "teacher"]),
            models.Index(fields=["institution", "subject"]),
        ]

    def __str__(self):
        return f"{self.teacher} -> {self.subject}"


class ClassDivision(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="class_divisions")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="class_divisions")
    name = models.CharField(max_length=255)
    section = models.CharField(max_length=32)

    class Meta:
        ordering = ["institution", "name", "section"]
        unique_together = ("institution", "department", "name", "section")
        indexes = [models.Index(fields=["institution", "department"])]

    def __str__(self):
        return f"{self.name} - {self.section} ({self.institution.name})"


# ---------------------------------------------------------------------------
# Calendar grid: unified for weekly-reset and rolling Day-Order institutions
# ---------------------------------------------------------------------------

class TimeSlot(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="time_slots")

    # 1..institution.cycle_length. Interpreted as weekday (Mon=1..Sat=6) for
    # School Edition, or Day-Order (Day 1..Day 6) for College Edition.
    day_identifier = models.PositiveSmallIntegerField()
    period_number = models.PositiveSmallIntegerField()

    start_time = models.TimeField()
    end_time = models.TimeField()
    is_break = models.BooleanField(default=False)

    class Meta:
        ordering = ["institution", "day_identifier", "period_number"]
        unique_together = ("institution", "day_identifier", "period_number")
        indexes = [models.Index(fields=["institution", "day_identifier"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_time__gt=F("start_time")),
                name="timeslot_end_after_start",
            ),
        ]

    def __str__(self):
        return f"Day {self.day_identifier} / P{self.period_number} ({self.institution.name})"


# ---------------------------------------------------------------------------
# Time grid configuration (Phase 2): drives TimeSlot auto-generation
# ---------------------------------------------------------------------------

class TimeGridConfig(models.Model):
    """
    One row per institution describing how to auto-generate its TimeSlot
    grid (core/services/timegrid.py) instead of hardcoding period times.

    `breaks` is a flexible list of dicts, each shaped
    {"after_period": <1..periods_per_day>, "duration_minutes": <int>},
    meaning "insert a break of this length after teaching period N".
    Multiple breaks (e.g. a short recess and a lunch break) are supported.
    """
    institution = models.OneToOneField(Institution, on_delete=models.CASCADE, related_name="time_grid_config")

    periods_per_day = models.PositiveSmallIntegerField()
    period_duration_minutes = models.PositiveSmallIntegerField()
    day_start_time = models.TimeField()
    breaks = models.JSONField(default=list, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(periods_per_day__gt=0), name="timegridconfig_periods_positive"),
            models.CheckConstraint(
                condition=Q(period_duration_minutes__gt=0), name="timegridconfig_duration_positive"
            ),
        ]

    def __str__(self):
        return f"TimeGridConfig({self.institution.name})"

    def clean(self):
        if not isinstance(self.breaks, list):
            raise ValidationError("breaks must be a list.")
        seen_after_periods = set()
        for entry in self.breaks:
            if not isinstance(entry, dict) or set(entry) != {"after_period", "duration_minutes"}:
                raise ValidationError(
                    "Each break must be a dict with exactly 'after_period' and 'duration_minutes' keys."
                )
            after_period = entry["after_period"]
            duration_minutes = entry["duration_minutes"]
            if not isinstance(after_period, int) or not (1 <= after_period <= self.periods_per_day):
                raise ValidationError(
                    f"break after_period={after_period!r} must be an int between 1 and periods_per_day."
                )
            if not isinstance(duration_minutes, int) or duration_minutes <= 0:
                raise ValidationError(f"break duration_minutes={duration_minutes!r} must be a positive int.")
            if after_period in seen_after_periods:
                raise ValidationError(f"Duplicate break after_period={after_period}.")
            seen_after_periods.add(after_period)


# ---------------------------------------------------------------------------
# Academic calendar (Phase 4c): maps real dates to the day_identifier cycle
# ---------------------------------------------------------------------------

class AcademicCalendarDay(models.Model):
    """
    One row per real calendar date for an institution, mapping it to the
    abstract day_identifier cycle that TimeSlot/TimetableCell/the solver
    already operate on. Built by core/services/calendar.py.

    day_identifier is null for any date with no classes -- a routine weekly
    off (is_holiday=False) or an explicit holiday (is_holiday=True). This is
    what Phase 4b's substitution engine will use to turn a real absence date
    (e.g. "Aug 15") into the abstract "Day 3" the rest of the schema speaks.
    """
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="calendar_days")
    date = models.DateField()
    day_identifier = models.PositiveSmallIntegerField(null=True, blank=True)
    is_holiday = models.BooleanField(default=False)
    label = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["institution", "date"]
        unique_together = ("institution", "date")
        indexes = [
            models.Index(fields=["institution", "date"]),
            models.Index(fields=["institution", "day_identifier"]),
        ]

    def __str__(self):
        return f"{self.date} -> Day {self.day_identifier} ({self.institution.name})"


# ---------------------------------------------------------------------------
# Elective parallelism support
# ---------------------------------------------------------------------------

class ElectiveGroup(models.Model):
    """
    Ties together CourseRequirement rows (often from different departments/
    class divisions) that must be scheduled into the same TimeSlot so
    students can split across parallel elective options. Placement is a
    Phase 3 solver concern; this table only records the grouping.
    """
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="elective_groups")
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="elective_groups")
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["institution", "term", "name"]
        unique_together = ("term", "name")
        indexes = [models.Index(fields=["institution", "term"])]

    def __str__(self):
        return f"{self.name} ({self.term.name})"


# ---------------------------------------------------------------------------
# What needs to be scheduled
# ---------------------------------------------------------------------------

class CourseRequirement(models.Model):
    """
    A demand line: 'this class division needs N periods/week of this subject'.
    The Phase 3 solver consumes these rows to populate TimetableCell.
    """
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="course_requirements")
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="course_requirements")
    class_division = models.ForeignKey(ClassDivision, on_delete=models.CASCADE, related_name="course_requirements")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="course_requirements")

    # Pre-assigned teacher is optional — the solver may assign one later.
    teacher = models.ForeignKey(
        Teacher, on_delete=models.SET_NULL, null=True, blank=True, related_name="course_requirements"
    )

    periods_per_week = models.PositiveSmallIntegerField()

    # Contiguous lab locking, e.g. a 6-hr weekly lab as two 3-hr blocks.
    is_lab = models.BooleanField(default=False)
    block_size = models.PositiveSmallIntegerField(default=1)

    elective_group = models.ForeignKey(
        ElectiveGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="course_requirements"
    )

    class Meta:
        ordering = ["institution", "term", "class_division", "subject"]
        unique_together = ("term", "class_division", "subject")
        indexes = [
            models.Index(fields=["institution", "term"]),
            models.Index(fields=["elective_group"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(periods_per_week__gt=0), name="coursereq_periods_positive"),
            models.CheckConstraint(condition=Q(block_size__gt=0), name="coursereq_block_size_positive"),
            models.CheckConstraint(
                condition=Q(block_size__lte=F("periods_per_week")),
                name="coursereq_block_not_exceed_weekly",
            ),
        ]

    def __str__(self):
        return f"{self.class_division} — {self.subject} ({self.periods_per_week}/wk)"


# ---------------------------------------------------------------------------
# Protected non-teaching windows
# ---------------------------------------------------------------------------

class FacultyDutyBlock(models.Model):
    """
    Reserves a TimeSlot against a teacher for non-teaching duties (paper
    valuation, invigilation, NAAC compliance, research), so the solver
    never schedules a class over it.
    """
    PAPER_VALUATION = "PAPER_VALUATION"
    INVIGILATION = "INVIGILATION"
    NAAC_COMPLIANCE = "NAAC_COMPLIANCE"
    RESEARCH = "RESEARCH"
    OTHER = "OTHER"
    DUTY_TYPE_CHOICES = [
        (PAPER_VALUATION, "Paper Valuation"),
        (INVIGILATION, "Invigilation"),
        (NAAC_COMPLIANCE, "NAAC Compliance"),
        (RESEARCH, "Research"),
        (OTHER, "Other"),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="faculty_duty_blocks")
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="faculty_duty_blocks")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="faculty_duty_blocks")
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name="duty_blocks")

    duty_type = models.CharField(max_length=20, choices=DUTY_TYPE_CHOICES)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["institution", "term", "teacher", "time_slot"]
        unique_together = ("term", "teacher", "time_slot")
        indexes = [models.Index(fields=["institution", "term", "teacher"])]

    def __str__(self):
        return f"{self.teacher} — {self.duty_type} ({self.time_slot})"


# ---------------------------------------------------------------------------
# The generated timetable itself
# ---------------------------------------------------------------------------

class TimetableCell(models.Model):
    """
    One occupied (class_division, time_slot) cell in a term's timetable.
    Hard constraints are enforced at the DB layer:
      - unique (term, class_division, time_slot) among non-elective cells
        ("no_double_booking_non_elective") -> no accidental class double-booking
      - unique (term, class_division, time_slot, subject), unconditional
        ("no_duplicate_subject_cell") -> for non-elective cells this is
        already implied by the constraint above; for elective cells (where
        several rows legitimately share a class_division + time_slot) it's
        what stops the same elective subject from occupying that slot twice
      - unique (term, teacher, time_slot)          -> no teacher double-booking

    `elective_group` is denormalized from course_requirement.elective_group
    (rather than joined through course_requirement) because course_requirement
    is SET_NULL on delete — if the constraints above relied on that join,
    a deleted CourseRequirement would silently reclassify an already-placed
    elective cell as "non-elective" and could collide with its own sibling.
    """
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="timetable_cells")
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="timetable_cells")
    class_division = models.ForeignKey(ClassDivision, on_delete=models.CASCADE, related_name="timetable_cells")
    time_slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE, related_name="timetable_cells")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="timetable_cells")
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="timetable_cells")

    course_requirement = models.ForeignKey(
        CourseRequirement, on_delete=models.SET_NULL, null=True, blank=True, related_name="timetable_cells"
    )
    elective_group = models.ForeignKey(
        ElectiveGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name="timetable_cells"
    )

    MANUAL = "MANUAL"
    RESIGNATION_RECOVERY = "RESIGNATION_RECOVERY"
    LOCKED_REASON_CHOICES = [
        (MANUAL, "Manual"),
        (RESIGNATION_RECOVERY, "Resignation Recovery"),
    ]

    # True for cells pinned by an admin or locked as part of a contiguous
    # lab block — protects them from being reshuffled during regeneration.
    is_locked = models.BooleanField(default=False)
    # Purely informational -- never read by any constraint/solver logic.
    # Lets an admin tell whether a locked cell is a deliberate pin, or a
    # temporary lock left over from a resignation-recovery run that should
    # already have unlocked it again (core/services/resignation.py).
    locked_reason = models.CharField(max_length=20, choices=LOCKED_REASON_CHOICES, blank=True, null=True)

    class Meta:
        ordering = ["institution", "term", "class_division", "time_slot"]
        constraints = [
            models.UniqueConstraint(
                fields=["term", "class_division", "time_slot"],
                condition=Q(elective_group__isnull=True),
                name="no_double_booking_non_elective",
            ),
            models.UniqueConstraint(
                fields=["term", "class_division", "time_slot", "subject"],
                name="no_duplicate_subject_cell",
            ),
            models.UniqueConstraint(
                fields=["term", "teacher", "time_slot"],
                name="timetablecell_unique_teacher_slot",
            ),
        ]
        indexes = [
            models.Index(fields=["institution", "term"]),
            models.Index(fields=["term", "class_division"]),
            models.Index(fields=["term", "teacher"]),
        ]

    def clean(self):
        # Belt-and-suspenders: catch cross-tenant mismatches before they
        # ever reach the DB constraints above.
        related = [self.term, self.class_division, self.time_slot, self.subject, self.teacher]
        if self.elective_group_id is not None:
            related.append(self.elective_group)
        if any(obj.institution_id != self.institution_id for obj in related):
            raise ValidationError("All related records must belong to the same institution as this cell.")

        if self.course_requirement_id is not None and self.course_requirement.elective_group_id != self.elective_group_id:
            raise ValidationError(
                "elective_group must match the originating course_requirement's elective_group."
            )

    def __str__(self):
        return f"{self.class_division} @ {self.time_slot} — {self.subject}"


# ---------------------------------------------------------------------------
# Solver run tracking (Phase 3)
# ---------------------------------------------------------------------------

class SolverRun(models.Model):
    """
    One invocation of the Phase 3 CP-SAT feasibility solver for a term.
    Tracks status/timing/errors so an async (Celery) solve can be observed
    without the caller having to hold a connection open for it.
    """
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (RUNNING, "Running"),
        (SUCCESS, "Success"),
        (FAILED, "Failed"),
    ]

    MANUAL = "MANUAL"
    RESIGNATION_RECOVERY = "RESIGNATION_RECOVERY"
    TRIGGER_CHOICES = [
        (MANUAL, "Manual"),
        (RESIGNATION_RECOVERY, "Resignation Recovery"),
    ]

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="solver_runs")
    term = models.ForeignKey(AcademicTerm, on_delete=models.CASCADE, related_name="solver_runs")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PENDING)
    trigger = models.CharField(max_length=20, choices=TRIGGER_CHOICES, default=MANUAL)
    celery_task_id = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    # Achieved weighted-objective value (lower is better) for a Phase 3b
    # optimized run; stays null for a feasibility-only (Phase 3a) run.
    objective_value = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["institution", "term"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"SolverRun({self.term.name}, {self.status})"


# ---------------------------------------------------------------------------
# Weighted objective configuration (Phase 3b)
# ---------------------------------------------------------------------------

class SolverWeightConfig(models.Model):
    """
    Per-institution weights for the Phase 3b weighted-sum quality objective
    (gap minimization, cognitive-load placement, fair afternoon rotation) —
    the admin "sliders" from the PRD. Higher weight = the solver works
    harder to avoid that penalty relative to the other two.
    """
    institution = models.OneToOneField(Institution, on_delete=models.CASCADE, related_name="solver_weight_config")
    gap_weight = models.PositiveSmallIntegerField(default=50)
    cognitive_load_weight = models.PositiveSmallIntegerField(default=50)
    fair_rotation_weight = models.PositiveSmallIntegerField(default=50)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(gap_weight__gte=0) & Q(gap_weight__lte=100)
                    & Q(cognitive_load_weight__gte=0) & Q(cognitive_load_weight__lte=100)
                    & Q(fair_rotation_weight__gte=0) & Q(fair_rotation_weight__lte=100)
                ),
                name="solverweightconfig_weights_in_range",
            ),
        ]

    def __str__(self):
        return f"SolverWeightConfig({self.institution.name})"
