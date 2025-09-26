"""Custom YAML dumper for handling multiline strings and special characters."""

import yaml


class CustomYAMLDumper(yaml.SafeDumper):
    """Custom YAML dumper class for proper handling of multiline strings."""

    def represent_str(self, data):
        """Represent strings with proper escaping and formatting."""
        # For empty strings or None, use default handling
        if not data:
            return self.represent_scalar("tag:yaml.org,2002:str", data or "")

        # Check if it contains characters that need special handling
        has_newlines = "\n" in data
        has_special_chars = any(c in data for c in ["\\", '"', "'", "\t", "\r"])
        is_long = len(data) > 80

        # Check if it needs literal style to avoid escaping
        needs_literal = (
            has_newlines
            or has_special_chars
            or is_long
            or any(
                c in data
                for c in [
                    "<",
                    ">",
                    "{",
                    "}",
                    "[",
                    "]",
                    "@",
                    "`",
                    "|",
                    "*",
                    "&",
                    "#",
                    "!",
                    "%",
                ]
            )
        )

        if needs_literal:
            return self.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        else:
            # Simple text uses default style
            return self.represent_scalar("tag:yaml.org,2002:str", data)

    def represent_none(self, data):
        """Represent None values as empty strings."""
        return self.represent_scalar("tag:yaml.org,2002:null", "")


# Register custom handlers
CustomYAMLDumper.add_representer(str, CustomYAMLDumper.represent_str)
CustomYAMLDumper.add_representer(type(None), CustomYAMLDumper.represent_none)