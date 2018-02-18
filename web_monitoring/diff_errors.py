class UndiffableContentError(ValueError):
    """
    Raised when the content provided to a differ is incompatible with the
    diff algorithm. For example, if a PDF was provided to an HTML differ.
    """


class UndecodableContentError(ValueError):
    """
    Raised when the content downloaded for diffing could not be decoded.
    """
