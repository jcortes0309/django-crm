jQuery(function($) {
	/* use jQuery-UI to apply a date picker to all crm-date-fields.  If you
	 * wish, substitute your JavaScript library of choice.
	 */
	$('.crm-date-field').datepicker({
		'dateFormat': 'mm/dd/yy'
	});
});