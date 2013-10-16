def thunderbird_rules(release):
    import StringIO
    fh = StringIO.StringIO()

    fh.write("""<?xml version="1.0" ?>\n""")
    fh.write("  <pgpRuleList>\n")
    key_ids = [str(key.kid) for key in release.active_keys]
    fh.write("""    <pgpRule email="{%s}" encrypt="2" keyId="%s" negateRule="0" pgpMime="2" sign="2"/>\n"""%(release.mailinglist.email,", ".join(key_ids)))
    fh.write("  </pgpRuleList>\n")
    content = fh.getvalue()
    fh.close()
    return content

    
def plot_over_time(mailinglists):
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d/%Y'))
    for mailinglist in mailinglists:
        x = [release.date for release in mailinglist.releases]
        y = [len(release.active_keys) for release in mailinglist.releases]

        plt.plot(x,y, linewidth=2.5, alpha=0.9, marker='o', label=mailinglist.name)

    plt.legend(loc='upper left')
    plt.gcf().set_size_inches(20,5) 
    plt.gcf().autofmt_xdate()
    plt.savefig(mailinglist.name + ".pdf")
