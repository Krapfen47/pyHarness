"""Three kinds of "no", kept apart on purpose.

They are used as labels: deep inside a tool, code simply raises one of these,
and ONE place (Toolbox.run / the controller) turns it into a result the model
reads. No tool has to build error dicts itself.

Why three and not one? Each tells the model something different, and each
has its own counter and limit:

    InvalidRequest  the reply was malformed (unknown tool, wrong arguments).
                    Nothing ran. The model must ask again -> counts as a RETRY.
    Denied          well-formed, but our policy says no (path outside the
                    repo, file outside the writable area, unknown check).
                    Asking the same thing again won't help -> counts as DENIED.
    ToolError       allowed, but it didn't work (file missing, text not
                    found). Trying differently may help -> counted as an error.
"""


class InvalidRequest(Exception):
    """The model's reply is not a valid action. Nothing was executed.

    `gate` names the check that said no, in the order the checks run:
    "json" (not JSON at all), "shape" (not one of the two allowed forms),
    "tool" (unknown tool name), "args" (wrong or oversized arguments).
    The GUI shows it as the red step of the validation pipeline.
    """

    def __init__(self, message: str, gate: str = "shape"):
        super().__init__(message)
        self.gate = gate


class Denied(Exception):
    """Policy refused the action."""


class ToolError(Exception):
    """The action was allowed but failed."""
