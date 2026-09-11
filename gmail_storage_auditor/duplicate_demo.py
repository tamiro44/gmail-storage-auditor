"""Run a fabricated original/forward/self-sent attachment analysis offline."""

from .demo import AS_OF
from .inventory import Attachment, Hint, Message, Page, Scope, collect_inventory
from .duplicates import analyze_duplicates
from .duplicate_report import render_duplicates


class DuplicateDemoReader:
    def read_page(self, scope: Scope, cursor: str | None) -> Page:
        attachment = Attachment("sample-slide.bin", 1024)
        return Page((
            Message("synthetic-original", thread_ref="synthetic-thread", direction="received",
                    attachments=(attachment,), attachments_complete=True,
                    hints=(Hint("original", "synthetic fixture"),)),
            Message("synthetic-forward", thread_ref="synthetic-thread", direction="sent",
                    attachments=(attachment,), attachments_complete=True,
                    hints=(Hint("forwarded", "synthetic fixture"),)),
            Message("synthetic-self", direction="self_sent", attachments=(attachment,)),
        ), complete=True)


def main() -> None:
    inventory = collect_inventory(DuplicateDemoReader(), Scope("duplicate examples", synthetic=True),
                                  as_of=AS_OF, max_pages=1)
    print(render_duplicates(analyze_duplicates(inventory)), end="")


if __name__ == "__main__":
    main()
