OLD_MODULE = "l10n_gt_fe_fiscal_values"
NEW_MODULE = "l10n_gt_fe"


def migrate(cr, version):
    """Merge technical ownership before the former add-on is removed."""
    cr.execute(
        "SELECT id, state FROM ir_module_module WHERE name = %s",
        [OLD_MODULE],
    )
    old_module = cr.fetchone()
    if not old_module:
        return

    old_module_id, old_state = old_module
    if old_state not in ("installed", "to upgrade", "to remove"):
        return

    # Both modules inherit the same core models.  Keep the XMLIDs already owned
    # by the destination and discard only the redundant aliases.
    cr.execute(
        """
        DELETE FROM ir_model_data AS old
              USING ir_model_data AS new
         WHERE old.module = %s
           AND new.module = %s
           AND old.name = new.name
           AND old.model = new.model
           AND old.res_id = new.res_id
        """,
        [OLD_MODULE, NEW_MODULE],
    )

    # Preserve endpoint parameters, views and field ownership under the
    # consolidated module so that its data files update the existing records.
    cr.execute(
        "UPDATE ir_model_data SET module = %s WHERE module = %s",
        [NEW_MODULE, OLD_MODULE],
    )

    # Redirect any third-party dependency to the consolidated module, avoiding
    # duplicate dependency rows where both names were already declared.
    cr.execute(
        """
        DELETE FROM ir_module_module_dependency AS old
              USING ir_module_module_dependency AS new
         WHERE old.name = %s
           AND new.name = %s
           AND old.module_id = new.module_id
        """,
        [OLD_MODULE, NEW_MODULE],
    )
    cr.execute(
        "UPDATE ir_module_module_dependency SET name = %s WHERE name = %s",
        [NEW_MODULE, OLD_MODULE],
    )

    # The old module has no standalone data left.  Removing its dependency rows
    # and state prevents a missing-addon warning on the following registry load.
    cr.execute(
        "DELETE FROM ir_module_module_dependency WHERE module_id = %s",
        [old_module_id],
    )
    cr.execute(
        """
        UPDATE ir_module_module
           SET state = 'uninstalled', latest_version = NULL
         WHERE id = %s
        """,
        [old_module_id],
    )
